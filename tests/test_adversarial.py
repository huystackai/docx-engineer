"""Separate skeptical review cases. Synthetic data; tests assert observable invariants."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import test_engine as fixture

engine, p, package, valid_body = fixture.engine, fixture.p, fixture.package, fixture.valid_body


class AdversarialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.doc = self.root / 'review.docx'

    def tearDown(self):
        self.tmp.cleanup()

    def patch(self, body):
        package(self.doc, body)
        pkg = engine.Package(self.doc)
        out = self.root / 'edited.docx'
        plan = {'input_sha256': pkg.digest, 'replacements': [{'paragraph': 0, 'old': 'Hello', 'new': 'Revised'}]}
        return pkg, plan, out

    def test_untouched_entity_bytes_not_normalized(self):
        pkg, plan, out = self.patch(p('Hello') + p(inline='<w:r><w:t>&#65; &#x42; untouched</w:t></w:r>'))
        engine.edit(pkg, plan, out)
        expected = pkg.parts['word/document.xml'].replace(b'>Hello</w:t>', b'>Revised</w:t>')
        self.assertEqual(engine.Package(out).parts['word/document.xml'], expected)

    def test_move_revision_cannot_be_silently_edited(self):
        pkg, plan, out = self.patch(p(inline='<w:moveFrom w:id="1"><w:r><w:t>Hello</w:t></w:r></w:moveFrom>'))
        with self.assertRaises(engine.EngineError):
            engine.edit(pkg, plan, out)
        self.assertFalse(out.exists())

    def test_bookmark_boundary_requires_capable_editor(self):
        pkg, plan, out = self.patch(p(inline='<w:bookmarkStart w:id="1" w:name="Target"/><w:r><w:t>Hello</w:t></w:r><w:bookmarkEnd w:id="1"/>'))
        with self.assertRaises(engine.EngineError):
            engine.edit(pkg, plan, out)

    def test_prose_reference_does_not_supply_missing_caption(self):
        package(self.doc, valid_body() + p(inline='<w:r><w:drawing/></w:r>') + p('See Figure 1 for the intended result.'))
        findings = engine.audit(engine.Package(self.doc))['findings']
        self.assertTrue(any(f['check'] == 'caption_coverage' and f['status'] == 'FAIL' for f in findings))

    def test_one_caption_cannot_cover_two_separate_figures(self):
        package(self.doc, valid_body() + p(inline='<w:r><w:drawing/></w:r>') + p('Figure 1. First image', 'Caption') + p(inline='<w:r><w:drawing/></w:r>'))
        findings = engine.audit(engine.Package(self.doc))['findings']
        self.assertTrue(any(f['check'] == 'caption_coverage' and f['status'] == 'FAIL' for f in findings))

    def test_caption_sequence_gap(self):
        package(self.doc, valid_body() + p('Figure 1. First', 'Caption') + p('Figure 3. Third', 'Caption'))
        findings = engine.audit(engine.Package(self.doc))['findings']
        self.assertTrue(any(f['check'] == 'caption_sequence' and f['status'] == 'FAIL' for f in findings))

    def test_vml_figure_without_caption_is_detected(self):
        package(self.doc, valid_body() + p(inline='<w:r><w:pict/></w:r>'))
        findings = engine.audit(engine.Package(self.doc))['findings']
        self.assertTrue(any(f['check'] == 'caption_coverage' and f['status'] == 'FAIL' for f in findings))

    def test_missing_header_relationship_is_detected(self):
        header = ('<w:hdr xmlns:w="' + fixture.W + '" xmlns:r="' + fixture.R + '">' + p(inline='<w:hyperlink r:id="unknown"><w:r><w:t>Link</w:t></w:r></w:hyperlink>') + '</w:hdr>').encode()
        package(self.doc, valid_body(), extra={'word/header1.xml': header})
        findings = engine.audit(engine.Package(self.doc))['findings']
        self.assertTrue(any(f['check'] == 'relationships' and f['status'] == 'FAIL' for f in findings))

    def test_utf16_dtd_not_bypassed(self):
        raw = ('<?xml version="1.0" encoding="utf-16"?><!DOCTYPE root [<!ENTITY x "expanded">]><root>&x;</root>').encode('utf-16')
        with self.assertRaises(engine.EngineError):
            engine.xml(raw)

    def test_cache_schema_is_validated_even_with_matching_digest(self):
        package(self.doc, valid_body())
        cache = self.root / 'cache'
        engine.audit(engine.Package(self.doc), cache_dir=cache)
        path = next(cache.glob('*.json'))
        entry = json.loads(path.read_text())
        entry['payload']['findings'] = [{'status': 'BANANA'}]
        entry['digest'] = engine.sha(json.dumps(entry['payload'], sort_keys=True).encode())
        path.write_text(json.dumps(entry))
        report = engine.audit(engine.Package(self.doc), cache_dir=cache)
        self.assertFalse(report['cache_hit'])

    def test_source_symlink_escape_cannot_pass(self):
        package(self.doc, p('Claim'))
        outside = self.root / 'outside.py'
        outside.write_text('proof')
        source_root = self.root / 'source'
        source_root.mkdir()
        (source_root / 'escape.py').symlink_to(outside)
        ledger = self.root / 'ledger.json'
        ledger.write_text(json.dumps({'schema_version': 1, 'claims': [{'id': 'C', 'text': 'Claim', 'sources': [{'path': 'escape.py', 'sha256': engine.sha(b'proof'), 'start_line': 1, 'end_line': 1, 'quote': 'proof'}]}]}))
        findings = engine.evidence_checks(engine.Package(self.doc), ledger, source_root)
        self.assertFalse(any(f['status'] == 'PASS' for f in findings))

    def test_failure_late_in_large_result_not_hidden_by_summary_cap(self):
        body = valid_body() + ''.join(p('Figure 1. Duplicate', 'Caption') for _ in range(110))
        package(self.doc, body)
        report = engine.audit(engine.Package(self.doc))
        self.assertGreater(len(report['findings']), 100)
        self.assertTrue(any(f['status'] == 'FAIL' for f in report['findings']))

    def test_unclosed_bookmark_cannot_make_reference_pass(self):
        inline = '<w:bookmarkStart w:id="1" w:name="target"/><w:r><w:t>Target</w:t></w:r><w:fldSimple w:instr=" REF target "/>'
        package(self.doc, valid_body() + p(inline=inline))
        findings = engine.audit(engine.Package(self.doc))['findings']
        self.assertTrue(any(f['check'] == 'bookmark_structure' and f['status'] == 'FAIL' for f in findings))

    def test_duplicate_bookmark_name_cannot_pass(self):
        inline = '<w:bookmarkStart w:id="1" w:name="target"/><w:bookmarkEnd w:id="1"/><w:bookmarkStart w:id="2" w:name="target"/><w:bookmarkEnd w:id="2"/>'
        package(self.doc, valid_body() + p(inline=inline))
        findings = engine.audit(engine.Package(self.doc))['findings']
        self.assertTrue(any(f['check'] == 'bookmark_structure' and f['status'] == 'FAIL' for f in findings))

    def test_non_utf8_declaration_patch_is_rejected(self):
        package(self.doc, p('Hello'), xml_prefix='<?xml version="1.0" encoding="ISO-8859-1"?>')
        pkg = engine.Package(self.doc)
        plan = {'input_sha256': pkg.digest, 'replacements': [{'paragraph': 0, 'old': 'Hello', 'new': 'Tiếng Việt'}]}
        out = self.root / 'edited.docx'
        with self.assertRaises(engine.EngineError):
            engine.edit(pkg, plan, out)
        self.assertFalse(out.exists())

    def test_publish_failure_leaves_no_partial_output(self):
        pkg, plan, out = self.patch(p('Hello'))
        with mock.patch.object(engine.os, 'link', side_effect=OSError('simulated publication failure')):
            with self.assertRaises(OSError):
                engine.edit(pkg, plan, out)
        self.assertFalse(out.exists())
        self.assertEqual(sorted(x.name for x in self.root.iterdir()), ['review.docx'])

    def test_cache_hit_cli_skips_package_parsing(self):
        package(self.doc, valid_body())
        cache = self.root / 'cache'
        engine.audit(engine.Package(self.doc), cache_dir=cache)
        with mock.patch.object(engine, 'Package', side_effect=AssertionError('unnecessary parse')):
            import contextlib, io
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                code = engine.main(['AUDIT', str(self.doc), '--cache-dir', str(cache)])
        self.assertEqual(code, 2)
        self.assertTrue(json.loads(captured.getvalue())['cache_hit'])

    def test_source_file_read_once_per_ledger_snapshot(self):
        package(self.doc, p('First claim') + p('Second claim'))
        source = self.root / 'proof.py'
        source.write_text('proof\n')
        anchor = {'path': 'proof.py', 'sha256': engine.sha(source.read_bytes()), 'start_line': 1, 'end_line': 1, 'quote': 'proof'}
        ledger = self.root / 'ledger.json'
        ledger.write_text(json.dumps({'schema_version': 1, 'claims': [{'id': '1', 'text': 'First claim', 'sources': [anchor]}, {'id': '2', 'text': 'Second claim', 'sources': [anchor]}]}))
        original = engine.bounded_read
        reads = []
        def recording(path, maximum):
            reads.append(Path(path).resolve())
            return original(path, maximum)
        pkg = engine.Package(self.doc)
        with mock.patch.object(engine, 'bounded_read', side_effect=recording):
            engine.evidence_checks(pkg, ledger, self.root)
        self.assertEqual(reads.count(source.resolve()), 1)

    def test_cache_wrong_payload_type_is_recomputed(self):
        package(self.doc, valid_body())
        cache = self.root / 'cache'
        engine.audit(engine.Package(self.doc), cache_dir=cache)
        path = next(cache.glob('*.json'))
        payload = []
        path.write_text(json.dumps({'payload': payload, 'digest': engine.sha(json.dumps(payload).encode())}))
        self.assertFalse(engine.audit(engine.Package(self.doc), cache_dir=cache)['cache_hit'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
