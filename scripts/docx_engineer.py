#!/usr/bin/env python3
"""Bounded OOXML checks and lossless text patches. Python standard library only."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from xml.parsers import expat
import zipfile

VERSION = "0.1.0"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"w": W}
MAX_PART = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024
PROFILES = {
    "ACADEMIC": {
        "introduction": ["introduction", "gioi thieu", "mo dau", "dat van de"],
        "methods": ["methods", "methodology", "phuong phap"],
        "results": ["results", "ket qua"],
        "discussion": ["discussion", "thao luan", "ban luan"],
        "references": ["references", "bibliography", "tai lieu tham khao"],
    },
    "HANDOVER": {
        "overview": ["overview", "tong quan", "gioi thieu"],
        "architecture": ["architecture", "kien truc"],
        "setup": ["setup", "installation", "cai dat", "moi truong", "huong dan phat trien"],
        "workflows": ["workflow", "luong", "chuc nang"],
        "api": ["api", "integration", "tich hop"],
        "testing": ["test", "kiem thu"],
        "limitations": ["limitation", "known issue", "gioi han", "van de da biet"],
        "handover": ["handover", "ban giao"],
    },
}


class EngineError(Exception):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normal(text):
    text = unicodedata.normalize("NFKD", text.lower().replace("đ", "d"))
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def xml(data):
    class NoDTD(ET.TreeBuilder):
        def doctype(self, name, pubid, system):
            raise EngineError("DTD/entity declarations are unsupported")
    try:
        return ET.fromstring(data, parser=ET.XMLParser(target=NoDTD()))
    except ET.ParseError as exc:
        raise EngineError("Malformed OOXML: " + str(exc)) from exc


def val(node, path, default=None):
    el = node.find(path, NS)
    return el.get("{" + W + "}val", default) if el is not None else default


def text_of(node):
    return "".join(e.text or "" for e in node.iter("{" + W + "}t"))


def finding(check, status, detail, locator="document", severity="Minor"):
    return dict(check=check, status=status, severity=severity, locator=locator, detail=detail)


def bounded_read(path, maximum):
    with Path(path).open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise EngineError("Input exceeds supported byte limit")
    return data


class Package:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.suffix.lower() != ".docx":
            raise EngineError("Only .docx is supported")
        self.raw = bounded_read(path, MAX_TOTAL)
        self.digest = sha(self.raw)
        try:
            with zipfile.ZipFile(io.BytesIO(self.raw)) as z:
                infos = z.infolist()
                names = [i.filename for i in infos]
                if len(names) != len(set(names)) or len(names) > 10000:
                    raise EngineError("Duplicate or excessive ZIP members")
                if sum(i.file_size for i in infos) > MAX_TOTAL:
                    raise EngineError("Expanded package exceeds supported limit")
                self.parts = {}
                for i in infos:
                    path_name = PurePosixPath(i.filename)
                    if i.flag_bits & 1 or path_name.is_absolute() or ".." in path_name.parts:
                        raise EngineError("Encrypted or unsafe ZIP member")
                    if i.file_size > MAX_PART:
                        raise EngineError("Package part exceeds supported limit")
                    self.parts[i.filename] = z.read(i)
                self.infos, self.comment = infos, z.comment
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
            raise EngineError("Unreadable DOCX package: " + str(exc)) from exc
        for name in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
            if name not in self.parts:
                raise EngineError("Missing required package part: " + name)
        self.trees = {n: xml(d) for n, d in self.parts.items()
                      if n.endswith((".xml", ".rels"))}
        self.doc = self.trees["word/document.xml"]
        if self.doc.tag != "{" + W + "}document" or self.doc.find("w:body", NS) is None:
            raise EngineError("Unsupported Word namespace or missing body")
        ct = self.trees["[Content_Types].xml"]
        main_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
        if not any(e.get("PartName") == "/word/document.xml" and e.get("ContentType") == main_type
                   for e in ct):
            raise EngineError("Unsupported or missing main content type")
        self.paragraphs = list(self.doc.iter("{" + W + "}p"))
        if len(self.paragraphs) > 100000:
            raise EngineError("Paragraph count exceeds supported limit")


def relationships(pkg):
    issues, external, part_ids = [], 0, {}
    office_main = False
    for name, tree in pkg.trees.items():
        if not name.endswith(".rels"):
            continue
        base = "" if name == "_rels/.rels" else str(PurePosixPath(name).parent.parent)
        ids = set()
        for rel in tree:
            rid, target = rel.get("Id"), rel.get("Target", "")
            if not rid or rid in ids:
                issues.append(finding("relationships", "FAIL", "Missing/duplicate relationship id", name, "Major"))
            ids.add(rid)
            if rel.get("TargetMode") == "External":
                external += 1
                continue
            # OPC internal targets are URI paths, not filesystem paths.
            from urllib.parse import unquote, urlsplit
            target_path = unquote(urlsplit(target).path)
            resolved = posixpath.normpath(target_path.lstrip("/") if target_path.startswith("/")
                                          else posixpath.join(base, target_path))
            if resolved.startswith("../") or resolved not in pkg.parts:
                issues.append(finding("relationships", "FAIL", "Missing/unsafe internal target: " + target,
                                      name, "Major"))
            if name == "_rels/.rels" and rel.get("Type", "").endswith("/officeDocument"):
                office_main = resolved == "word/document.xml"
        owner = posixpath.join(base, PurePosixPath(name).name[:-5])
        part_ids[owner] = ids
    if not office_main:
        issues.append(finding("relationships", "FAIL", "Root officeDocument relationship is missing/wrong", severity="Major"))
    for name, tree in pkg.trees.items():
        if not name.startswith("word/") or not name.endswith(".xml"):
            continue
        for e in tree.iter():
            for attr in ("id", "embed", "link"):
                rid = e.get("{" + R + "}" + attr)
                if rid and rid not in part_ids.get(name, set()):
                    issues.append(finding("relationships", "FAIL", "Unresolved part relationship: " + rid, name, "Major"))
    if not issues:
        issues.append(finding("relationships", "PASS", "Internal relationships resolve"))
    if external:
        issues.append(finding("external_references", "UNVERIFIED", f"{external} external targets not fetched"))
    return issues


def heading_level(p, styles):
    direct = val(p, "w:pPr/w:outlineLvl")
    if direct is not None:
        return int(direct) + 1 if direct.isdigit() and int(direct) < 9 else None
    sid = val(p, "w:pPr/w:pStyle", "")
    seen = set()
    while sid and sid not in seen:
        seen.add(sid)
        style = styles.get(sid)
        if style is not None:
            outline = val(style, "w:pPr/w:outlineLvl")
            if outline is not None:
                return int(outline) + 1 if outline.isdigit() and int(outline) < 9 else None
        m = re.fullmatch(r"Heading\s*([1-9])", sid, re.I)
        if m:
            return int(m[1])
        sid = val(style, "w:basedOn", "") if style is not None else ""
    return None


def inspect(pkg, profile, requirements):
    issues = [finding("package", "PASS", "Bounded OOXML package parsed")]
    issues.extend(relationships(pkg))
    style_tree = pkg.trees.get("word/styles.xml")
    styles = {s.get("{" + W + "}styleId"): s for s in style_tree} if style_tree is not None else {}
    headings, previous, manual = [], 0, {}
    duplicates = {}
    for i, p in enumerate(pkg.paragraphs):
        t = text_of(p)
        level = heading_level(p, styles)
        loc = f"word/document.xml:p[{i}]"
        if level:
            headings.append(dict(paragraph=i, level=level, text=t[:160]))
            if level > previous + 1:
                issues.append(finding("heading_hierarchy", "FAIL", f"Level {previous} to {level}", loc, "Major"))
            previous = level
            m = re.match(r"^\s*(\d+(?:\.\d+)*)(?:[.)\s]|$)", t)
            if m:
                number = tuple(int(v) for v in m[1].split("."))
                parent = manual.get(level - 1)
                prior = manual.get(level)
                if len(number) != level or (parent and number[:-1] != parent):
                    issues.append(finding("heading_numbering", "FAIL", "Manual heading number disagrees with hierarchy", loc))
                elif prior and prior[:-1] == number[:-1] and number[-1] != prior[-1] + 1:
                    issues.append(finding("heading_numbering", "FAIL", "Duplicate/skipped manual heading number", loc))
                manual[level] = number
            else:
                manual.pop(level, None)
            for key in list(manual):
                if key > level:
                    del manual[key]
        elif len(normal(t)) >= 80:
            k = normal(t)
            if k in duplicates:
                issues.append(finding("duplicate_content", "UNVERIFIED", f"Repeated long paragraph; first at p[{duplicates[k]}]", loc))
            else:
                duplicates[k] = i
    if not any(f["check"] == "heading_hierarchy" for f in issues):
        issues.append(finding("heading_hierarchy", "PASS", f"No skipped level among {len(headings)} headings"))
    for name, aliases in requirements.items():
        found = any(any(normal(alias) in normal(h["text"]) for alias in aliases) for h in headings)
        issues.append(finding("section_coverage", "PASS" if found else "FAIL", name, severity="Major"))
    num_tree = pkg.trees.get("word/numbering.xml")
    nums, abstracts = {}, set()
    if num_tree is not None:
        abstracts = {x.get("{" + W + "}abstractNumId") for x in num_tree.findall("w:abstractNum", NS)}
        nums = {x.get("{" + W + "}numId"): val(x, "w:abstractNumId") for x in num_tree.findall("w:num", NS)}
    numbered = list(pkg.doc.findall(".//w:numPr/w:numId", NS))
    for style in styles.values():
        numbered.extend(style.findall("w:pPr/w:numPr/w:numId", NS))
    for x in numbered:
        nid = x.get("{" + W + "}val")
        if nid != "0" and (nid not in nums or nums[nid] not in abstracts):
            issues.append(finding("numbering_definitions", "FAIL", "Unresolved numId/abstractNum: " + str(nid), severity="Major"))
    issues.append(finding("automatic_numbering_display", "UNVERIFIED" if numbered else "NOT APPLICABLE",
                          "Rendered sequence/restarts need visual review" if numbered else "No numbering references"))
    issues.extend(captions(pkg, profile))
    issues.extend(references(pkg))
    for name, tree in pkg.trees.items():
        if name.startswith("word/") and (tree.findall(".//w:txbxContent", NS) or
                                         name in ("word/footnotes.xml", "word/endnotes.xml")):
            issues.append(finding("complex_content", "UNVERIFIED", "Review text boxes/notes separately", name))
    issues.extend([
        finding("factual_consistency", "UNVERIFIED", "Requires semantic review; no general contradiction detector"),
        finding("writing_quality", "UNVERIFIED", "Requires profile-aware editorial review"),
        finding("visual_layout", "UNVERIFIED", "Requires successful render and all-page inspection of this exact hash"),
        finding("bibliographic_references", "UNVERIFIED" if profile == "ACADEMIC" else "NOT APPLICABLE",
                "Citation existence/accuracy requires supplied bibliography and source review"),
    ])
    tables = list(pkg.doc.iter("{" + W + "}tbl"))
    return dict(schema_version=1, engine_version=VERSION, document_sha256=pkg.digest,
                profile=profile, inventory=dict(bytes=len(pkg.raw), parts=len(pkg.parts),
                paragraphs=len(pkg.paragraphs), tables=len(tables),
                drawings=len(list(pkg.doc.iter("{" + W + "}drawing"))), headings=headings[:100]),
                findings=issues)


CAPTION = re.compile(r"\b(Figure|Fig\.?|Hình|Table|Bảng)\s+(\d+(?:\.\d+)*)(?!\d)", re.I)


def caption_keys(text):
    return [("figure" if normal(m[1]).startswith(("fig", "hinh")) else "table", m[2])
            for m in CAPTION.finditer(text)]


def captions(pkg, profile):
    issues, seen, count = [], {}, {"figure": 0, "table": 0}
    caption_blocks, previous, used = {}, {}, {}
    blocks = [e for e in pkg.doc.find("w:body", NS) if text_of(e).strip() or
              e.findall(".//w:drawing", NS) or e.findall(".//w:pict", NS) or e.tag == "{" + W + "}tbl"]
    for i, block in enumerate(blocks):
        if block.tag == "{" + W + "}p":
            keys = caption_keys(text_of(block))
            # Restrict to Caption style or a caption-like paragraph start.
            is_caption = val(block, "w:pPr/w:pStyle", "").lower() == "caption" or bool(
                re.match(r"^\s*(Figure|Fig\.?|Hình|Table|Bảng)\s+\d", text_of(block), re.I))
            if is_caption:
                caption_blocks[i] = keys
                for key in keys:
                    count[key[0]] += 1
                    if key in seen:
                        issues.append(finding("caption_duplicates", "FAIL", "Duplicate caption " + str(key), f"block[{i}]"))
                    seen[key] = i
                    number = tuple(int(v) for v in key[1].split("."))
                    prev = previous.get((key[0], number[:-1]))
                    if prev is not None and number[-1] > prev + 1:
                        issues.append(finding("caption_sequence", "FAIL", "Skipped caption number: " + key[1], f"block[{i}]"))
                    previous[(key[0], number[:-1])] = number[-1]
    for i, block in enumerate(blocks):
        kind = "table" if block.tag == "{" + W + "}tbl" else "figure"
        objects = 1 if kind == "table" else len(block.findall(".//w:drawing", NS)) + len(block.findall(".//w:pict", NS))
        if not objects:
            continue
        labels = 0
        for candidate in (i, i + 1, i - 1):
            available = sum(k[0] == kind for k in caption_blocks.get(candidate, [])) - used.get((candidate, kind), 0)
            take = min(max(available, 0), objects - labels)
            labels += take
            used[(candidate, kind)] = used.get((candidate, kind), 0) + take
        if labels < objects and (kind == "figure" or profile == "ACADEMIC"):
            issues.append(finding("caption_coverage", "FAIL", f"{objects} {kind} object(s), {labels} nearby label(s)", f"block[{i}]"))
        if kind == "table":
            rows = block.findall("w:tr", NS)
            if len(rows) > 20 and not any(r.find("w:trPr/w:tblHeader", NS) is not None for r in rows[:2]):
                issues.append(finding("long_table", "UNVERIFIED", f"{len(rows)} rows without repeated header; inspect pagination", f"block[{i}]"))
    if not any(f["check"].startswith("caption") for f in issues):
        issues.append(finding("captions", "PASS", f"No detected label defects; figures={count['figure']}, tables={count['table']}"))
    return issues


def references(pkg):
    issues, fields = [], []
    bookmarks = set()
    for name, tree in pkg.trees.items():
        if not name.startswith("word/"):
            continue
        starts, ends, names = {}, set(), set()
        for e in tree.iter():
            if e.tag == "{" + W + "}bookmarkStart":
                bid, bname = e.get("{" + W + "}id"), e.get("{" + W + "}name")
                if not bid or not bname or bid in starts or bname in names:
                    issues.append(finding("bookmark_structure", "FAIL", "Missing/duplicate bookmark id or name", name))
                starts[bid] = bname
                names.add(bname)
            elif e.tag == "{" + W + "}bookmarkEnd":
                bid = e.get("{" + W + "}id")
                if bid not in starts or bid in ends:
                    issues.append(finding("bookmark_structure", "FAIL", "Unmatched bookmark end", name))
                ends.add(bid)
        if set(starts) != ends:
            issues.append(finding("bookmark_structure", "FAIL", "Unclosed bookmark range", name))
        bookmarks.update(names)
        stack = []
        for e in tree.iter():
            if e.tag == "{" + W + "}fldChar":
                typ = e.get("{" + W + "}fldCharType")
                if typ == "begin":
                    stack.append("")
                elif typ == "end":
                    if stack:
                        fields.append(stack.pop())
                    else:
                        issues.append(finding("field_structure", "FAIL", "Unmatched field end", name))
            elif e.tag == "{" + W + "}instrText" and stack:
                stack[-1] += e.text or ""
            elif e.tag == "{" + W + "}fldSimple":
                fields.append(e.get("{" + W + "}instr", ""))
        if stack:
            issues.append(finding("field_structure", "FAIL", "Unclosed field", name))
    for instr in fields:
        m = re.match(r'\s*(?:REF|PAGEREF|NOTEREF)\s+(?:"([^"]+)"|(\S+))', instr, re.I)
        if m and (m[1] or m[2]) not in bookmarks:
            issues.append(finding("cross_references", "FAIL", "Missing bookmark: " + (m[1] or m[2]), severity="Major"))
    for name, tree in pkg.trees.items():
        if name.startswith("word/"):
            for e in tree.findall(".//w:hyperlink", NS):
                anchor = e.get("{" + W + "}anchor")
                if anchor and anchor not in bookmarks:
                    issues.append(finding("cross_references", "FAIL", "Missing hyperlink anchor: " + anchor, name))
    if not issues:
        issues.append(finding("cross_references", "PASS", "Parsed internal bookmark references resolve"))
    return issues


def evidence_checks(pkg, ledger_path, source_root):
    if not ledger_path:
        return [finding("source_evidence", "UNVERIFIED", "No claim ledger supplied")]
    ledger = json.loads(bounded_read(ledger_path, MAX_SOURCE))
    if not isinstance(ledger, dict) or ledger.get("schema_version") != 1 or not isinstance(ledger.get("claims"), list):
        raise EngineError("Invalid evidence ledger schema")
    if not source_root:
        return [finding("source_evidence", "UNVERIFIED", "Source root unavailable")]
    root = Path(source_root).resolve()
    document = "\n".join(text_of(p) for p in pkg.paragraphs)
    issues, subjects, ids, source_snapshot = [], {}, set(), {}
    for entry in ledger["claims"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not isinstance(entry.get("text"), str):
            raise EngineError("Malformed claim")
        cid = entry["id"]
        if not cid or cid in ids:
            raise EngineError("Missing/duplicate claim id")
        ids.add(cid)
        if not entry["text"] or entry["text"] not in document:
            issues.append(finding("evidence_anchor", "FAIL", "Claim text absent from document", cid, "Major"))
        subject, value = entry.get("subject"), entry.get("value")
        if subject is not None:
            if not isinstance(subject, str) or not isinstance(value, str):
                raise EngineError("Subject and value must be strings")
            if subject in subjects and subjects[subject] != value:
                issues.append(finding("claim_conflict", "FAIL", "Conflicting values for " + subject, cid, "Major"))
            subjects[subject] = value
        sources = entry.get("sources", [])
        if not isinstance(sources, list):
            raise EngineError("Claim sources must be a list")
        if not sources:
            issues.append(finding("evidence_integrity", "UNVERIFIED", "No source anchors", cid))
        for s in sources:
            try:
                if not isinstance(s, dict) or not isinstance(s.get("path"), str) or Path(s["path"]).is_absolute():
                    raise EngineError("Source path must be relative")
                path = (root / s["path"]).resolve()
                if not path.is_relative_to(root):
                    raise EngineError("Source path escapes root")
                if path not in source_snapshot:
                    source_snapshot[path] = bounded_read(path, MAX_SOURCE)
                raw = source_snapshot[path]
                start, end, quote = s.get("start_line"), s.get("end_line"), s.get("quote")
                if type(start) is not int or type(end) is not int or not 1 <= start <= end <= start + 199:
                    raise EngineError("Invalid/broad source range")
                lines = raw.decode("utf-8").splitlines()
                if end > len(lines) or not isinstance(quote, str) or not quote:
                    raise EngineError("Missing source range/quote")
                if s.get("sha256") != sha(raw) or quote not in "\n".join(lines[start - 1:end]):
                    issues.append(finding("evidence_integrity", "FAIL", "Stale hash or unmatched source quote", cid, "Major"))
                else:
                    issues.append(finding("evidence_integrity", "PASS", "Source hash and bounded quote match", cid))
            except (EngineError, OSError, UnicodeError) as exc:
                issues.append(finding("evidence_integrity", "UNVERIFIED", str(exc), cid, "Major"))
        issues.append(finding("claim_semantics", "UNVERIFIED", "Anchors alone do not establish implementation or truth", cid))
    if not ledger["claims"]:
        issues.append(finding("source_evidence", "UNVERIFIED", "Empty claim ledger"))
    return issues


def text_spans(data):
    """Expat byte offsets keep all untouched XML bytes and namespace prefixes."""
    parser = expat.ParserCreate(namespace_separator="}")
    paragraphs, stack, current_text = [], [], None
    protected = {"fldSimple", "fldChar", "instrText", "hyperlink", "drawing", "pict", "ins", "del",
                 "moveFrom", "moveTo", "bookmarkStart", "bookmarkEnd", "sdt", "customXml", "smartTag",
                 "tab", "br", "sym", "object", "AlternateContent", "footnoteReference", "endnoteReference"}

    def tag_end(offset):
        quote = None
        for i in range(offset, len(data)):
            char = data[i]
            if quote:
                if char == quote:
                    quote = None
            elif char in (34, 39):
                quote = char
            elif char == 62:
                return i + 1
        raise EngineError("Unterminated tag")

    def start(name, attrs):
        nonlocal current_text
        local = name.split("}")[-1]
        if local == "p" and name == W + "}p":
            ancestors = {x.split("}")[-1] for x in stack}
            paragraphs.append(dict(nodes=[], protected=bool(ancestors & protected)))
        active = W + "}p" in stack or name == W + "}p"
        formatting = any(s in (W + "}pPr", W + "}rPr") for s in stack)
        unsupported = (not name.startswith(W + "}") or
                       (not formatting and local not in {"p", "pPr", "r", "rPr", "t"}))
        if paragraphs and active and (local in protected or unsupported):
            paragraphs[-1]["protected"] = True
        if name == W + "}t" and paragraphs:
            offset = parser.CurrentByteIndex
            end = tag_end(offset)
            if data[offset:end].rstrip().endswith(b"/>"):
                current_text = None
            else:
                current_text = dict(start=end, tag_start=offset, end=None, text="")
                paragraphs[-1]["nodes"].append(current_text)
        stack.append(name)

    def end(name):
        nonlocal current_text
        if name == W + "}t" and current_text is not None:
            current_text["end"] = parser.CurrentByteIndex
            current_text = None
        stack.pop()

    def chars(value):
        if current_text is not None:
            current_text["text"] += value

    parser.StartElementHandler, parser.EndElementHandler, parser.CharacterDataHandler = start, end, chars
    parser.Parse(data, True)
    for p in paragraphs:
        for n in p["nodes"]:
            n["original_text"] = n["text"]
    return paragraphs


def edit(pkg, plan, output):
    if not isinstance(plan, dict) or plan.get("input_sha256") != pkg.digest:
        raise EngineError("Edit plan has wrong/missing input SHA256")
    if any(n.startswith("_xmlsignatures/") for n in pkg.parts):
        raise EngineError("Signed packages cannot be patched")
    output = Path(output)
    if output.suffix.lower() != ".docx" or output.resolve() == pkg.path.resolve() or output.exists():
        raise EngineError("Output must be a distinct, new .docx path")
    operations = plan.get("replacements")
    if not isinstance(operations, list) or not operations:
        raise EngineError("Nonempty replacements list required")
    data = pkg.parts["word/document.xml"]
    try:
        data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise EngineError("Text patcher supports UTF-8 OOXML only") from exc
    declaration = re.match(rb'(?:\xef\xbb\xbf)?<\?xml\b[^?]*\?>', data)
    encoding = re.search(rb'encoding\s*=\s*([\'"])(.*?)\1', declaration[0], re.I) if declaration else None
    if encoding and encoding[2].lower() not in (b'utf-8', b'utf8'):
        raise EngineError("Text patcher supports UTF-8 declarations only")
    spans = text_spans(data)
    for op in operations:
        if not isinstance(op, dict) or type(op.get("paragraph")) is not int or not 0 <= op["paragraph"] < len(spans):
            raise EngineError("Invalid paragraph index")
        old, new = op.get("old"), op.get("new")
        if not isinstance(old, str) or not old or not isinstance(new, str) or any(ord(c) < 32 for c in new):
            raise EngineError("Replacement must be nonempty old text and new text without controls")
        p = spans[op["paragraph"]]
        if p["protected"]:
            raise EngineError("Complex/protected paragraph requires capable document editor")
        nodes = p["nodes"]
        full = "".join(n["text"] for n in nodes)
        if full.count(old) != 1:
            raise EngineError("Replacement must match exactly once")
        begin, finish = full.index(old), full.index(old) + len(old)
        position, inserted = 0, False
        for n in nodes:
            original = n["text"]
            left, right = position, position + len(original)
            position = right
            if right <= begin or left >= finish:
                continue
            prefix = original[:max(0, begin - left)]
            suffix = original[max(0, finish - left):] if finish < right else ""
            n["text"] = prefix + (new if not inserted else "") + suffix
            inserted = True
    from xml.sax.saxutils import escape
    patches = []
    for p in spans:
        for n in p["nodes"]:
            if n["text"] == n["original_text"]:
                continue
            original = data[n["start"]:n["end"]]
            replacement = escape(n["text"]).encode("utf-8")
            if replacement != original:
                patches.append((n["start"], n["end"], replacement))
                if n["text"][:1].isspace() or n["text"][-1:].isspace():
                    tag = data[n["tag_start"]:n["start"]]
                    if b"xml:space=" in tag:
                        changed = re.sub(rb'xml:space=([\'"])\w+\1', b'xml:space="preserve"', tag)
                    else:
                        changed = tag[:-1] + b' xml:space="preserve">'
                    if changed != tag:
                        patches.append((n["tag_start"], n["start"], changed))
    for start, end, replacement in sorted(patches, reverse=True):
        data = data[:start] + replacement + data[end:]
    xml(data)  # Never publish malformed XML.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.comment = pkg.comment
        for info in pkg.infos:
            z.writestr(info, data if info.filename == "word/document.xml" else pkg.parts[info.filename])
    candidate = buffer.getvalue()
    # Publish a fully written sibling using an exclusive hard link, never a partial destination.
    fd, temporary = tempfile.mkstemp(dir=output.parent, prefix=".docx-engineer-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(candidate)
        os.link(temporary, output)
    finally:
        os.unlink(temporary)
    return dict(status="UNVERIFIED", operation="EDIT", output=str(output), input_sha256=pkg.digest,
                output_sha256=sha(candidate), replacements=len(operations),
                changed_parts=["word/document.xml"], visual_qa="UNVERIFIED",
                note="Text patch completed; final semantic and all-page visual QA required")


def validate_requirements(value):
    if not isinstance(value, dict) or not value or any(
            not isinstance(k, str) or not isinstance(v, list) or not v or
            any(not isinstance(a, str) or not a.strip() for a in v) for k, v in value.items()):
        raise EngineError("Requirements must be a nonempty object of alias lists")
    return value


def cache_location(digest, profile, requirements, cache_dir):
    engine = sha(Path(__file__).read_bytes())
    key = sha(json.dumps([digest, engine, profile, requirements], sort_keys=True).encode())
    return Path(cache_dir) / (key + ".json") if cache_dir else None


def load_cache(cache_file, digest, profile):
    if cache_file and cache_file.exists():
        try:
            entry = json.loads(bounded_read(cache_file, MAX_PART))
            payload = entry["payload"]
            valid_findings = isinstance(payload, dict) and isinstance(payload.get("findings"), list) and all(
                isinstance(f, dict) and f.get("status") in {"PASS", "FAIL", "UNVERIFIED", "NOT APPLICABLE"}
                and all(isinstance(f.get(k), str) for k in ("check", "severity", "locator", "detail"))
                for f in payload["findings"])
            if (valid_findings and payload.get("schema_version") == 1 and payload.get("profile") == profile
                    and isinstance(payload.get("inventory"), dict) and payload["findings"]
                    and entry["digest"] == sha(json.dumps(payload, sort_keys=True).encode())
                    and payload["document_sha256"] == digest):
                payload["cache_hit"] = True
                return payload
        except (KeyError, TypeError, ValueError, OSError, EngineError):
            pass
    return None


def audit(pkg, profile="HANDOVER", requirements=None, cache_dir=None):
    requirements = validate_requirements(requirements if requirements is not None else PROFILES[profile])
    cache_file = cache_location(pkg.digest, profile, requirements, cache_dir)
    cached = load_cache(cache_file, pkg.digest, profile)
    if cached is not None:
        return cached
    report = inspect(pkg, profile, requirements)
    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        entry = dict(payload=report, digest=sha(json.dumps(report, sort_keys=True).encode()))
        fd, tmp = tempfile.mkstemp(dir=cache_file.parent, prefix=".cache-")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(entry, stream, ensure_ascii=False)
            os.replace(tmp, cache_file)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    report["cache_hit"] = False
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", type=str.lower, choices=["audit", "verify", "edit"])
    parser.add_argument("document")
    parser.add_argument("--profile", type=str.upper, choices=list(PROFILES), default="HANDOVER")
    parser.add_argument("--requirements")
    parser.add_argument("--evidence")
    parser.add_argument("--source-root")
    parser.add_argument("--cache-dir")
    parser.add_argument("--paragraphs", help="Optional START:END, at most 40 paragraphs")
    parser.add_argument("--plan")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.mode == "edit":
            pkg = Package(args.document)
            if not args.plan or not args.output:
                raise EngineError("EDIT requires --plan and --output")
            report = edit(pkg, json.loads(bounded_read(args.plan, MAX_SOURCE)), args.output)
        else:
            req = json.loads(bounded_read(args.requirements, MAX_SOURCE))["required_sections"] if args.requirements else None
            req = validate_requirements(req if req is not None else PROFILES[args.profile])
            report, pkg = None, None
            if args.cache_dir and not args.evidence and not args.paragraphs:
                if Path(args.document).suffix.lower() != ".docx":
                    raise EngineError("Only .docx is supported")
                digest = sha(bounded_read(args.document, MAX_TOTAL))
                report = load_cache(cache_location(digest, args.profile, req, args.cache_dir), digest, args.profile)
            if report is None:
                pkg = Package(args.document)
                report = audit(pkg, args.profile, req, args.cache_dir)
            report["findings"].extend(evidence_checks(pkg, args.evidence, args.source_root))
            if args.paragraphs:
                a, b = [int(x) for x in args.paragraphs.split(":")]
                if not 0 <= a <= b <= len(pkg.paragraphs) or b - a > 40:
                    raise EngineError("Invalid/broad paragraph range")
                report["paragraphs"] = [dict(index=i, text=text_of(pkg.paragraphs[i])[:600]) for i in range(a, b)]
            statuses = {f["status"] for f in report["findings"]}
            report["status"] = "FAIL" if "FAIL" in statuses else "UNVERIFIED" if "UNVERIFIED" in statuses else "PASS"
            report["finding_count"] = len(report["findings"])
            report["findings"] = sorted(report["findings"], key=lambda f: (f["status"] != "FAIL", f["severity"] != "Major"))[:100]
            report["findings_truncated"] = report["finding_count"] > 100
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["status"] == "FAIL" else 2 if report["status"] == "UNVERIFIED" else 0
    except (EngineError, OSError, ValueError, KeyError, TypeError, expat.ExpatError) as exc:
        print(json.dumps(dict(status="FAIL", error=str(exc), severity="Major"), ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
