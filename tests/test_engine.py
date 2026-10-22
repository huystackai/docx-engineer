"""Synthetic OOXML fixtures only; no user documents or network calls."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from xml.sax.saxutils import escape
import zipfile

SPEC = importlib.util.spec_from_file_location("engine", Path(__file__).parents[1] / "scripts/docx_engineer.py")
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)
OBSERVATIONS = []
W, R = engine.W, engine.R


def p(text="", style=None, inline=None):
    properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{properties}' + (inline if inline is not None else f'<w:r><w:t>{escape(text)}</w:t></w:r>') + '</w:p>'


def table(rows=2, repeat=False, complex_cells=False):
    values = []
    for i in range(rows):
        props = '<w:trPr><w:tblHeader/></w:trPr>' if i == 0 and repeat else ''
        cell = '<w:tcPr><w:gridSpan w:val="2"/></w:tcPr>' if i == 0 and complex_cells else ''
        values.append(f'<w:tr>{props}<w:tc>{cell}{p("Row " + str(i))}</w:tc></w:tr>')
    return '<w:tbl><w:tblPr><w:tblW w:w="7000" w:type="dxa"/></w:tblPr><w:tblGrid><w:gridCol w:w="3500"/><w:gridCol w:w="3500"/></w:tblGrid>' + ''.join(values) + '</w:tbl>'


def package(path, body, extra=None, styles=None, docrels=None, xml_prefix=''):
    types = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    root_rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="' + R + '/officeDocument" Target="word/document.xml"/></Relationships>'
    document = xml_prefix + '<w:document xmlns:w="' + W + '" xmlns:r="' + R + '"><w:body>' + body + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>'
    parts = {'[Content_Types].xml': types.encode(), '_rels/.rels': root_rels.encode(),
             'word/document.xml': document.encode(),
             'word/styles.xml': (styles or '<w:styles xmlns:w="' + W + '"><w:style w:type="paragraph" w:styleId="Heading1"><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style></w:styles>').encode()}
    if docrels:
        parts['word/_rels/document.xml.rels'] = docrels.encode()
    parts.update(extra or {})
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.comment = b'preserve archive comment'
        for name, data in parts.items():
            z.writestr(name, data)
    return path


def valid_body(profile='HANDOVER'):
    return ''.join(p(aliases[0].title(), 'Heading1') + p('Content describing this section.')
                   for aliases in engine.PROFILES[profile].values())


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.doc = self.root / 'fixture.docx'

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, body=None, profile='HANDOVER', **kwargs):
        package(self.doc, body if body is not None else valid_body(profile), **kwargs)
        return engine.audit(engine.Package(self.doc), profile)

    def statuses(self, report, check):
        return [f['status'] for f in report['findings'] if f['check'] == check]

    def expect(self, report, check, status):
        actual = self.statuses(report, check)
        OBSERVATIONS.append(dict(test=self.id().split('.')[-1], check=check, expected=status, actual=actual))
        self.assertIn(status, actual)

    def test_valid_handover_no_structural_false_fail(self):
        report = self.report()
        self.assertFalse([f for f in report['findings'] if f['status'] == 'FAIL'])
        self.expect(report, 'section_coverage', 'PASS')
        self.expect(report, 'visual_layout', 'UNVERIFIED')

    def test_valid_academic_no_structural_false_fail(self):
        report = self.report(profile='ACADEMIC')
        self.assertFalse([f for f in report['findings'] if f['status'] == 'FAIL'])
        self.expect(report, 'bibliographic_references', 'UNVERIFIED')

    def test_skipped_heading_level(self):
        self.expect(self.report(p('Overview', 'Heading1') + p('Nested', 'Heading3')), 'heading_hierarchy', 'FAIL')

    def test_missing_section(self):
        self.expect(self.report(p('Overview', 'Heading1')), 'section_coverage', 'FAIL')

    def test_inherited_heading_level(self):
        styles = '<w:styles xmlns:w="' + W + '"><w:style w:styleId="Custom"><w:basedOn w:val="Base"/></w:style><w:style w:styleId="Base"><w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style></w:styles>'
        self.expect(self.report(p('Nested', 'Custom'), styles=styles), 'heading_hierarchy', 'FAIL')

    def test_wrong_manual_heading_number(self):
        self.expect(self.report(p('1 Overview', 'Heading1') + p('2.1 Detail', 'Heading2')), 'heading_numbering', 'FAIL')

    def test_skipped_manual_heading_number(self):
        self.expect(self.report(p('1 Overview', 'Heading1') + p('3 Architecture', 'Heading1')), 'heading_numbering', 'FAIL')

    def test_missing_numbering_definition(self):
        self.expect(self.report(p(inline='<w:pPr><w:numPr><w:numId w:val="9"/></w:numPr></w:pPr><w:r><w:t>Item</w:t></w:r>')),
                    'numbering_definitions', 'FAIL')

    def test_valid_numbering_definitions(self):
        numbering = ('<w:numbering xmlns:w="' + W + '"><w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl></w:abstractNum><w:num w:numId="7"><w:abstractNumId w:val="1"/></w:num></w:numbering>').encode()
        report = self.report(valid_body() + p(inline='<w:pPr><w:numPr><w:numId w:val="7"/></w:numPr></w:pPr><w:r><w:t>Item</w:t></w:r>'), extra={'word/numbering.xml': numbering})
        self.assertNotIn('FAIL', self.statuses(report, 'numbering_definitions'))
        self.expect(report, 'automatic_numbering_display', 'UNVERIFIED')

    def test_duplicate_caption(self):
        self.expect(self.report(p('Figure 1. One', 'Caption') + p('Figure 1. Two', 'Caption')), 'caption_duplicates', 'FAIL')

    def test_missing_figure_caption(self):
        self.expect(self.report(p(inline='<w:r><w:drawing/></w:r>')), 'caption_coverage', 'FAIL')

    def test_valid_figure_caption(self):
        report = self.report(valid_body() + p(inline='<w:r><w:drawing/></w:r>') + p('Figure 1. Architecture', 'Caption'))
        self.assertNotIn('FAIL', self.statuses(report, 'caption_coverage'))

    def test_missing_academic_table_caption(self):
        self.expect(self.report(valid_body('ACADEMIC') + table(), 'ACADEMIC'), 'caption_coverage', 'FAIL')

    def test_long_complex_table(self):
        report = self.report(valid_body('ACADEMIC') + p('Table 1. Long data', 'Caption') + table(55, True, True), 'ACADEMIC')
        self.assertEqual(report['inventory']['tables'], 1)
        self.assertFalse([f for f in report['findings'] if f['status'] == 'FAIL'])
        self.expect(report, 'visual_layout', 'UNVERIFIED')

    def test_long_table_without_header_risk(self):
        self.expect(self.report(valid_body() + table(50)), 'long_table', 'UNVERIFIED')

    def test_duplicated_paragraph_requires_semantic_review(self):
        text = 'A detailed paragraph describing the application and its operational limitations for maintainers. '
        self.expect(self.report(valid_body() + p(text) + p(text)), 'duplicate_content', 'UNVERIFIED')

    def test_dangling_hyperlink(self):
        self.expect(self.report(p(inline='<w:hyperlink w:anchor="missing"><w:r><w:t>See section</w:t></w:r></w:hyperlink>')), 'cross_references', 'FAIL')

    def test_broken_split_complex_reference(self):
        inline = '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGE</w:instrText></w:r><w:r><w:instrText>REF absent </w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>'
        self.expect(self.report(p(inline=inline)), 'cross_references', 'FAIL')

    def test_valid_simple_reference(self):
        inline = '<w:bookmarkStart w:id="0" w:name="exists"/><w:r><w:t>Target</w:t></w:r><w:bookmarkEnd w:id="0"/><w:fldSimple w:instr=" REF exists "><w:r><w:t>Target</w:t></w:r></w:fldSimple>'
        report = self.report(valid_body() + p(inline=inline))
        self.expect(report, 'cross_references', 'PASS')

    def test_unclosed_field(self):
        self.expect(self.report(p(inline='<w:r><w:fldChar w:fldCharType="begin"/></w:r>')), 'field_structure', 'FAIL')

    def test_missing_internal_relationship_target(self):
        rel = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId2" Type="' + R + '/image" Target="media/missing.png"/></Relationships>'
        self.expect(self.report(valid_body(), docrels=rel), 'relationships', 'FAIL')

    def test_external_link_is_not_fetched_or_passed(self):
        rel = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId2" Type="' + R + '/hyperlink" TargetMode="External" Target="https://example.invalid/"/></Relationships>'
        self.expect(self.report(valid_body(), docrels=rel), 'external_references', 'UNVERIFIED')

    def test_corrupted_and_unsupported(self):
        self.doc.write_bytes(b'corrupt')
        with self.assertRaises(engine.EngineError):
            engine.Package(self.doc)
        other = self.root / 'legacy.doc'
        other.write_bytes(b'legacy')
        with self.assertRaises(engine.EngineError):
            engine.Package(other)

    def test_malformed_xml_part(self):
        package(self.doc, valid_body(), extra={'word/header1.xml': b'<broken'})
        with self.assertRaises(engine.EngineError):
            engine.Package(self.doc)

    def test_dtd_rejected(self):
        package(self.doc, valid_body(), xml_prefix='<!DOCTYPE w:document [<!ENTITY x "expanded">]>')
        with self.assertRaises(engine.EngineError):
            engine.Package(self.doc)

    def test_missing_source_never_passes(self):
        package(self.doc, p('Offline sync is implemented.'))
        ledger = self.root / 'ledger.json'
        ledger.write_text(json.dumps({'schema_version': 1, 'claims': [{'id': 'C1', 'text': 'Offline sync is implemented.', 'sources': []}]}))
        findings = engine.evidence_checks(engine.Package(self.doc), ledger, self.root)
        self.assertFalse([f for f in findings if f['status'] == 'PASS'])

    def test_conflicting_technical_claims(self):
        package(self.doc, p('Sync is implemented.') + p('Sync is not implemented.'))
        ledger = self.root / 'ledger.json'
        ledger.write_text(json.dumps({'schema_version': 1, 'claims': [
            {'id': 'C1', 'text': 'Sync is implemented.', 'subject': 'sync', 'value': 'implemented'},
            {'id': 'C2', 'text': 'Sync is not implemented.', 'subject': 'sync', 'value': 'not implemented'}]}))
        findings = engine.evidence_checks(engine.Package(self.doc), ledger, self.root)
        self.assertIn('FAIL', [f['status'] for f in findings if f['check'] == 'claim_conflict'])

    def ledger(self):
        source = self.root / 'client.py'
        source.write_text('def lookup():\n    return False\n')
        package(self.doc, p('The client calls lookup'))
        entry = {'id': 'C1', 'text': 'The client calls lookup', 'sources': [{'path': 'client.py', 'sha256': engine.sha(source.read_bytes()), 'start_line': 1, 'end_line': 2, 'quote': 'def lookup'}]}
        ledger = self.root / 'ledger.json'
        ledger.write_text(json.dumps({'schema_version': 1, 'claims': [entry]}))
        return source, ledger

    def test_matching_quote_does_not_prove_implementation(self):
        source, ledger = self.ledger()
        findings = engine.evidence_checks(engine.Package(self.doc), ledger, self.root)
        self.assertIn('PASS', [f['status'] for f in findings if f['check'] == 'evidence_integrity'])
        self.assertIn('UNVERIFIED', [f['status'] for f in findings if f['check'] == 'claim_semantics'])

    def test_stale_source_hash_invalidates_evidence(self):
        source, ledger = self.ledger()
        source.write_text('def lookup():\n    return True\n')
        findings = engine.evidence_checks(engine.Package(self.doc), ledger, self.root)
        self.assertIn('FAIL', [f['status'] for f in findings if f['check'] == 'evidence_integrity'])

    def test_cache_hits_and_invalidates_document_and_requirements(self):
        package(self.doc, valid_body())
        cache = self.root / 'cache'
        one = engine.audit(engine.Package(self.doc), cache_dir=cache)
        two = engine.audit(engine.Package(self.doc), cache_dir=cache)
        self.assertFalse(one['cache_hit'])
        self.assertTrue(two['cache_hit'])
        three = engine.audit(engine.Package(self.doc), requirements={'other': ['Missing']}, cache_dir=cache)
        self.assertFalse(three['cache_hit'])
        package(self.doc, valid_body() + p('Changed'))
        self.assertFalse(engine.audit(engine.Package(self.doc), cache_dir=cache)['cache_hit'])

    def test_corrupt_cache_recomputed(self):
        package(self.doc, valid_body())
        cache = self.root / 'cache'
        engine.audit(engine.Package(self.doc), cache_dir=cache)
        next(cache.glob('*.json')).write_text('{bad')
        self.assertFalse(engine.audit(engine.Package(self.doc), cache_dir=cache)['cache_hit'])

    def test_audit_read_only(self):
        package(self.doc, valid_body())
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        engine.audit(engine.Package(self.doc))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def plan(self, pkg, old='Hello world', new='Hello reader', paragraph=0):
        return {'input_sha256': pkg.digest, 'replacements': [{'paragraph': paragraph, 'old': old, 'new': new}]}

    def test_edit_split_runs_preserves_properties_and_other_parts(self):
        inline = '<w:r><w:rPr><w:b/><w:color w:val="126633"/></w:rPr><w:t>Hello </w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>world</w:t></w:r>'
        package(self.doc, p(inline=inline) + table(30, True, True), extra={'word/media/image1.png': b'unchanged image bytes'})
        original = self.doc.read_bytes()
        pkg = engine.Package(self.doc)
        target = self.root / 'edited.docx'
        engine.edit(pkg, self.plan(pkg), target)
        output = engine.Package(target)
        self.assertEqual(self.doc.read_bytes(), original)
        self.assertEqual(engine.text_of(output.paragraphs[0]), 'Hello reader')
        self.assertIn(b'<w:rPr><w:b/><w:color w:val="126633"/></w:rPr>', output.parts['word/document.xml'])
        self.assertIn(b'<w:rPr><w:i/></w:rPr>', output.parts['word/document.xml'])
        self.assertIn(b'xml:space="preserve"', output.parts['word/document.xml']) if b'>Hello </w:t>' in output.parts['word/document.xml'] else None
        for name in pkg.parts:
            if name != 'word/document.xml':
                self.assertEqual(pkg.parts[name], output.parts[name], name)
        self.assertEqual(pkg.comment, output.comment)

    def test_atomic_validation_of_multiple_replacements(self):
        package(self.doc, p('Hello world'))
        pkg = engine.Package(self.doc)
        plan = self.plan(pkg)
        plan['replacements'].append({'paragraph': 0, 'old': 'missing', 'new': 'text'})
        output = self.root / 'edited.docx'
        with self.assertRaises(engine.EngineError):
            engine.edit(pkg, plan, output)
        self.assertFalse(output.exists())

    def test_stale_plan_and_existing_output_rejected(self):
        package(self.doc, p('Hello world'))
        pkg = engine.Package(self.doc)
        plan = self.plan(pkg)
        plan['input_sha256'] = '0' * 64
        output = self.root / 'edited.docx'
        with self.assertRaises(engine.EngineError):
            engine.edit(pkg, plan, output)
        output.write_bytes(b'keep')
        with self.assertRaises(engine.EngineError):
            engine.edit(pkg, self.plan(pkg), output)
        self.assertEqual(output.read_bytes(), b'keep')

    def test_protected_field_edit_rejected(self):
        package(self.doc, p(inline='<w:fldSimple w:instr=" PAGE "><w:r><w:t>Hello world</w:t></w:r></w:fldSimple>'))
        pkg = engine.Package(self.doc)
        with self.assertRaises(engine.EngineError):
            engine.edit(pkg, self.plan(pkg), self.root / 'edited.docx')

    def test_signed_package_edit_rejected(self):
        package(self.doc, p('Hello world'), extra={'_xmlsignatures/sig1.xml': b'<signature/>'})
        pkg = engine.Package(self.doc)
        with self.assertRaises(engine.EngineError):
            engine.edit(pkg, self.plan(pkg), self.root / 'edited.docx')

    def test_cli_errors_are_machine_readable(self):
        self.doc.write_bytes(b'broken')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = engine.main(['verify', str(self.doc)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())['status'], 'FAIL')


class RecordedResult(unittest.TextTestResult):
    records = []

    def addSuccess(self, test):
        self.records.append(dict(test=test.id(), expected='PASS', actual='PASS'))
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.records.append(dict(test=test.id(), expected='PASS', actual='FAIL'))
        super().addFailure(test, err)

    def addError(self, test, err):
        self.records.append(dict(test=test.id(), expected='PASS', actual='ERROR'))
        super().addError(test, err)


if __name__ == '__main__':
    report_path = None
    if '--report' in sys.argv:
        i = sys.argv.index('--report')
        report_path = Path(sys.argv[i + 1])
        del sys.argv[i:i + 2]
    runner = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    if report_path:
        report_path.write_text(json.dumps(dict(tests=result.testsRun, failures=len(result.failures),
                                              errors=len(result.errors), results=result.records,
                                              observations=OBSERVATIONS), indent=2))
    sys.exit(not result.wasSuccessful())
