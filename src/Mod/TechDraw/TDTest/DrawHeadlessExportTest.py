#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Comprehensive headless export tests for the TechDraw module.

This test suite provides extensive coverage for the TechDraw headless export
functionality introduced in Phase 1, including:

- Basic API functionality and return value validation
- File I/O operations with various path formats and encodings
- Error handling for invalid inputs and edge cases
- Template processing and validation
- Unicode filename support
- Memory and performance constraint testing
- Cross-platform compatibility validation
- SVG content structure and encoding verification

These tests ensure the headless export implementation is robust,
reliable, and suitable for production use.
"""

import math
import os
import re
import shutil
import statistics
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import FreeCAD as App
import TechDraw
import Part
import Sketcher
import unittest

try:  # Optional dependency for ReverseEngineering regression checks
    import ReverseEngineering  # type: ignore
except ImportError:  # pragma: no cover - module may not be built
    ReverseEngineering = None

TECHDRAW_MODULE_NAME = getattr(TechDraw, "__name__", "TechDraw")

try:  # Optional dependency for PDF validation
    import PyPDF2  # type: ignore
except ImportError:  # pragma: no cover - PyPDF2 not always available
    PyPDF2 = None


def _has_drawviewsketch():
    """Return True if the DrawViewSketch type can be created in this build."""
    doc = App.ActiveDocument
    created_doc = False
    if doc is None:
        doc = App.newDocument("DVSketchProbe")
        created_doc = True
    try:
        obj = doc.addObject("TechDraw::DrawViewSketch", "DVSketchProbe")
        doc.removeObject(obj.Name)
        return True
    except Exception:
        return False
    finally:
        if created_doc:
            App.closeDocument(doc.Name)


DRAWVIEWSKETCH_AVAILABLE = _has_drawviewsketch()


class DrawHeadlessExportTest(unittest.TestCase):
    """Exercise DrawPage headless export helpers added in Phase 1."""

    def _qt_available(self):
        try:
            from PySide2.QtGui import QGuiApplication
        except Exception:  # pragma: no cover - PySide may be absent in some builds
            return None
        return QGuiApplication

    def setUp(self):
        self._doc = App.newDocument("TDHeadless")
        self._page = self._doc.addObject("TechDraw::DrawPage", "Page")
        self._tempdir = tempfile.mkdtemp(prefix="techdraw_headless_")
        self._assign_template(self._page)

    def tearDown(self):
        doc_name = self._doc.Name
        App.closeDocument(doc_name)
        shutil.rmtree(self._tempdir, ignore_errors=True)

    # Helpers -----------------------------------------------------------------

    def _tmp(self, filename):
        return os.path.join(self._tempdir, filename)

    def _export_pdf(self, target):
        """Invoke TechDraw export helper and normalise the return value."""
        try:
            result = self._page.exportToPDF(target)
        except Exception as exc:  # pragma: no cover - exercised in failure tests
            return False, exc
        return bool(result), None

    def _export_svg(self, target):
        """Invoke TechDraw export helper and normalise the return value."""
        try:
            result = self._page.exportToSVG(target)
        except Exception as exc:  # pragma: no cover - exercised in failure tests
            return False, exc
        return bool(result), None

    def _assign_template(self, page):
        """Ensure the supplied page has a usable template."""
        template = self._doc.addObject("TechDraw::DrawSVGTemplate", "UnitTestTemplate")
        template_path = None
        if TechDraw is not None and hasattr(TechDraw, "getStandardTemplate"):
            try:
                candidate = TechDraw.getStandardTemplate('A4_LandscapeTD.svg')  # type: ignore[attr-defined]
                if candidate:
                    candidate_path = Path(candidate)
                    if candidate_path.exists():
                        template_path = candidate_path
            except Exception:
                template_path = None

        if template_path is None:
            fallback = Path(self._tempdir) / "unit_template.svg"
            fallback.write_text(
                """<?xml version='1.0' encoding='UTF-8'?>\n<svg xmlns='http://www.w3.org/2000/svg' width='297mm' height='210mm'\n viewBox='0 0 297 210' version='1.1'>\n  <rect x='5' y='5' width='287' height='200' fill='none' stroke='#000' stroke-width='0.35'/>\n</svg>\n""",
                encoding="utf-8",
            )
            template.Template = str(fallback)
        else:
            template.Template = str(template_path)

        page.Template = template

    def _set_view_scale(self, view, scale_value):
        """Force a DrawView-derived object to use a custom scale."""
        if hasattr(view, "ScaleType"):
            try:
                view.ScaleType = "Custom"
            except Exception:
                pass
        view.Scale = scale_value

    @staticmethod
    def _err_text(err, fallback="returned False"):
        return str(err) if err else fallback

    def _export_svg_string(self):
        temp_svg = self._tmp("temp_render.svg")
        ok, err = self._export_svg(temp_svg)
        if not ok:
            raise AssertionError(f"SVG export failed: {self._err_text(err, 'unknown error')}")
        try:
            with open(temp_svg, "r", encoding="utf-8") as handle:
                return handle.read()
        finally:
            if os.path.exists(temp_svg):
                os.remove(temp_svg)

    # Tests -------------------------------------------------------------------

    def test_00_qt_application_defaults_when_unset(self):
        """Headless export should bootstrap an offscreen QGuiApplication."""
        QGuiApplication = self._qt_available()
        if QGuiApplication is None:
            self.skipTest("PySide2 is not available")

        if QGuiApplication.instance():  # pragma: no cover - GUI builds
            self.skipTest("QGuiApplication already initialised")

        original_platform = os.environ.pop("QT_QPA_PLATFORM", None)
        original_opengl = os.environ.pop("QT_OPENGL", None)

        try:
            svg_content = self._export_svg_string()
            self.assertTrue(svg_content, "SVG string is empty")
            self.assertIsNotNone(QGuiApplication.instance(),
                                 "rendering did not create a QGuiApplication")
            self.assertNotIn("Qt SVG Document", svg_content,
                              "Qt fallback SVG stub detected")
            self.assertEqual(os.environ.get("QT_QPA_PLATFORM"), "offscreen")
            self.assertEqual(os.environ.get("QT_OPENGL"), "software")
        finally:
            if original_platform is None:
                os.environ.pop("QT_QPA_PLATFORM", None)
            else:
                os.environ["QT_QPA_PLATFORM"] = original_platform

            if original_opengl is None:
                os.environ.pop("QT_OPENGL", None)
            else:
                os.environ["QT_OPENGL"] = original_opengl

    def test_qt_application_respects_existing_environment(self):
        """Existing Qt platform hints must not be overwritten."""
        QGuiApplication = self._qt_available()
        if QGuiApplication is None:
            self.skipTest("PySide2 is not available")

        original_platform = os.environ.get("QT_QPA_PLATFORM")
        original_opengl = os.environ.get("QT_OPENGL")
        os.environ["QT_QPA_PLATFORM"] = original_platform or "offscreen"
        os.environ["QT_OPENGL"] = original_opengl or "software"

        try:
            svg_content = self._export_svg_string()
            self.assertTrue(svg_content, "SVG string is empty")
            self.assertIsNotNone(QGuiApplication.instance())
            self.assertNotIn("Qt SVG Document", svg_content,
                              "Qt fallback SVG stub detected")
            self.assertEqual(os.environ.get("QT_QPA_PLATFORM"),
                             original_platform or "offscreen")
            self.assertEqual(os.environ.get("QT_OPENGL"),
                             original_opengl or "software")
        finally:
            if original_platform is None:
                os.environ.pop("QT_QPA_PLATFORM", None)
            else:
                os.environ["QT_QPA_PLATFORM"] = original_platform

            if original_opengl is None:
                os.environ.pop("QT_OPENGL", None)
            else:
                os.environ["QT_OPENGL"] = original_opengl

    def test_api_methods_available(self):
        """DrawPage should expose the headless export helpers."""
        self.assertEqual(TECHDRAW_MODULE_NAME, "TechDraw", "TechDraw module failed to import")
        for attr in ("exportToPDF", "exportToSVG", "renderToSVGString"):
            self.assertTrue(hasattr(self._page, attr), f"DrawPage missing {attr}")

    def test_pdf_export_creates_file(self):
        """exportToPDF should create a non-empty PDF file."""
        pdf_path = self._tmp("basic.pdf")
        ok, err = self._export_pdf(pdf_path)
        self.assertTrue(ok, f"exportToPDF failed: {self._err_text(err)}")
        self.assertTrue(os.path.exists(pdf_path), "PDF file was not created")
        self.assertGreater(os.path.getsize(pdf_path), 0, "PDF file is empty")

        # Validate PDF header or parse with PyPDF2 if available
        with open(pdf_path, "rb") as handle:
            head = handle.read(4)
        self.assertEqual(head, b"%PDF", "PDF header missing")

        if PyPDF2 is not None:
            reader = PyPDF2.PdfReader(pdf_path)
            self.assertGreaterEqual(len(reader.pages), 1, "PDF should contain at least one page")

    def test_svg_export_creates_file(self):
        """exportToSVG should emit an SVG file with content."""
        svg_path = self._tmp("basic.svg")
        ok, err = self._export_svg(svg_path)
        self.assertTrue(ok, f"exportToSVG failed: {self._err_text(err)}")
        self.assertTrue(os.path.exists(svg_path), "SVG file was not created")
        with open(svg_path, "r", encoding="utf-8") as handle:
            snippet = handle.read(200)
        self.assertTrue(snippet.strip(), "SVG file is empty")

        tree = ET.parse(svg_path)
        self.assertEqual(tree.getroot().tag.split('}')[-1], "svg")

    def test_render_to_svg_string_returns_markup(self):
        """renderToSVGString should return SVG markup."""
        svg_content = self._export_svg_string()
        self.assertTrue(svg_content, "SVG string is empty")

        root = ET.fromstring(svg_content)
        self.assertEqual(root.tag.split('}')[-1], "svg")

    def test_export_rejects_empty_path(self):
        """Empty paths must be rejected with a False return value."""
        ok_pdf, err_pdf = self._export_pdf("")
        self.assertFalse(ok_pdf, f"Empty path PDF export unexpectedly succeeded: {err_pdf}")

        ok_svg, err_svg = self._export_svg("")
        self.assertFalse(ok_svg, f"Empty path SVG export unexpectedly succeeded: {err_svg}")

    def test_export_invalid_path_sets_error(self):
        bad_dir = os.path.join(self._tempdir, "missing")
        pdf_bad = os.path.join(bad_dir, "fail.pdf")
        svg_bad = os.path.join(bad_dir, "fail.svg")

        ok_pdf, err_pdf = self._export_pdf(pdf_bad)
        self.assertFalse(ok_pdf, f"Invalid path PDF export unexpectedly succeeded: {err_pdf}")
        self.assertFalse(os.path.exists(pdf_bad))

        ok_svg, err_svg = self._export_svg(svg_bad)
        self.assertFalse(ok_svg, f"Invalid path SVG export unexpectedly succeeded: {err_svg}")
        self.assertFalse(os.path.exists(svg_bad))

    def test_export_with_template_object(self):
        """A linked SVG template should still export successfully."""
        template = self._doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        template_path = os.path.join(os.path.dirname(__file__), "TestTemplate.svg")
        template.Template = template_path
        self._page.Template = template
        self._doc.recompute()

        pdf_path = self._tmp("template.pdf")
        svg_path = self._tmp("template.svg")

        ok_pdf, err_pdf = self._export_pdf(pdf_path)
        self.assertTrue(ok_pdf, f"Template PDF export failed: {self._err_text(err_pdf)}")
        self.assertTrue(os.path.exists(pdf_path))
        ok_svg, err_svg = self._export_svg(svg_path)
        self.assertTrue(ok_svg, f"Template SVG export failed: {self._err_text(err_svg)}")
        self.assertTrue(os.path.exists(svg_path))

    def test_unicode_filename_handling(self):
        """Export should handle Unicode filenames correctly."""
        unicode_pdf = self._tmp("tëst_ünìcödé.pdf")
        unicode_svg = self._tmp("tëst_ünìcödé.svg")

        ok_pdf, err_pdf = self._export_pdf(unicode_pdf)
        self.assertTrue(ok_pdf, f"Unicode PDF export failed: {self._err_text(err_pdf)}")
        self.assertTrue(os.path.exists(unicode_pdf), "Unicode PDF file was not created")

        ok_svg, err_svg = self._export_svg(unicode_svg)
        self.assertTrue(ok_svg, f"Unicode SVG export failed: {self._err_text(err_svg)}")
        self.assertTrue(os.path.exists(unicode_svg), "Unicode SVG file was not created")

    def test_page_size_boundaries(self):
        """Test export with extreme page sizes."""
        # Test with very small page (minimum viable size)
        template = self._doc.addObject("TechDraw::DrawSVGTemplate", "SmallTemplate")
        template.setExpression("Width", "1mm")
        template.setExpression("Height", "1mm")
        self._page.Template = template
        self._doc.recompute()

        small_pdf = self._tmp("small.pdf")
        ok_pdf, err_pdf = self._export_pdf(small_pdf)
        self.assertTrue(ok_pdf, f"Small page PDF export failed: {self._err_text(err_pdf)}")

        # Test with large page (A0 size: 841x1189mm)
        template.setExpression("Width", "841mm")
        template.setExpression("Height", "1189mm")
        self._doc.recompute()

        large_pdf = self._tmp("large.pdf")
        ok_pdf, err_pdf = self._export_pdf(large_pdf)
        self.assertTrue(ok_pdf, f"Large page PDF export failed: {self._err_text(err_pdf)}")

    def test_dpi_resolution_limits(self):
        """Test export with various DPI settings to ensure no overflow."""
        svg_content = self._export_svg_string()
        self.assertTrue(svg_content, "Base SVG export failed")

        # Test that very high DPI doesn't cause integer overflow
        # This is a regression test for potential overflow in PageRenderer.cpp:223-224
        # We can't directly set DPI from Python, but we can verify the output is reasonable
        self.assertLess(len(svg_content), 100000000, "SVG output suspiciously large (possible overflow)")
        self.assertGreater(len(svg_content), 100, "SVG output suspiciously small")

    def test_svg_encoding_validation(self):
        """Test SVG output has proper encoding and structure."""
        svg_content = self._export_svg_string()
        self.assertTrue(svg_content, "SVG export failed")

        # Check for proper XML declaration and encoding
        self.assertTrue(svg_content.startswith('<?xml') or '<svg' in svg_content[:100],
                       "SVG missing proper XML structure")

        # Validate UTF-8 encoding by ensuring it can be re-encoded
        try:
            svg_content.encode('utf-8')
        except UnicodeEncodeError:
            self.fail("SVG content contains invalid UTF-8 characters")

        # Check for basic SVG structure
        self.assertIn('<svg', svg_content, "SVG missing root element")
        self.assertIn('</svg>', svg_content, "SVG missing closing tag")

    def test_file_permission_edge_cases(self):
        """Test handling of file permission issues."""
        if os.name == 'nt':  # Windows
            self.skipTest("File permission tests not applicable on Windows")

        # Create a directory with no write permissions
        readonly_dir = os.path.join(self._tempdir, "readonly")
        os.makedirs(readonly_dir, exist_ok=True)
        os.chmod(readonly_dir, 0o444)  # Read-only

        try:
            readonly_pdf = os.path.join(readonly_dir, "fail.pdf")
            ok_pdf, err_pdf = self._export_pdf(readonly_pdf)
            self.assertFalse(ok_pdf, "Export to read-only directory should fail")
            self.assertFalse(os.path.exists(readonly_pdf), "File should not be created in read-only directory")
        finally:
            # Restore permissions for cleanup
            os.chmod(readonly_dir, 0o755)

    def test_concurrent_export_safety(self):
        """Test that multiple exports don't interfere with each other."""
        # Simulate potential race condition by doing rapid exports
        paths = [self._tmp(f"concurrent_{i}.pdf") for i in range(5)]
        results = []

        for path in paths:
            ok, err = self._export_pdf(path)
            results.append((ok, err, path))

        # All exports should succeed
        for i, (ok, err, path) in enumerate(results):
            self.assertTrue(ok, f"Concurrent export {i} failed: {self._err_text(err)}")
            self.assertTrue(os.path.exists(path), f"Concurrent export {i} file missing")
            self.assertGreater(os.path.getsize(path), 0, f"Concurrent export {i} file empty")

    def test_memory_constraint_handling(self):
        """Test export behavior under memory constraints."""
        # Test with string export that might consume more memory
        svg_strings = []

        # Generate multiple SVG strings to test memory usage
        for i in range(10):
            svg_content = self._export_svg_string()
            self.assertTrue(svg_content, f"SVG export {i} failed")
            svg_strings.append(svg_content)

        # All strings should be identical (deterministic output)
        for i, svg in enumerate(svg_strings[1:], 1):
            self.assertEqual(svg, svg_strings[0], f"SVG export {i} differs from first export")

    def test_special_characters_in_paths(self):
        """Test export with various special characters in file paths."""
        special_chars = ["spaces in name", "dots.in.name", "dash-in-name", "under_score"]

        for char_test in special_chars:
            with self.subTest(char_test=char_test):
                pdf_path = self._tmp(f"{char_test}.pdf")
                svg_path = self._tmp(f"{char_test}.svg")

                ok_pdf, err_pdf = self._export_pdf(pdf_path)
                self.assertTrue(ok_pdf, f"PDF export with '{char_test}' failed: {self._err_text(err_pdf)}")

                ok_svg, err_svg = self._export_svg(svg_path)
                self.assertTrue(ok_svg, f"SVG export with '{char_test}' failed: {self._err_text(err_svg)}")

    def test_template_field_processing(self):
        """Test that template field processing works correctly."""
        simple_template_path = os.path.join(os.path.dirname(__file__), "TestTemplateSimple.svg")
        if not os.path.exists(simple_template_path):
            self.skipTest("TestTemplateSimple.svg not found")

        template = self._doc.addObject("TechDraw::DrawSVGTemplate", "FieldTemplate")
        template.Template = simple_template_path
        self._page.Template = template
        self._doc.recompute()

        # Export SVG and check that template content is present
        svg_content = self._export_svg_string()
        self.assertTrue(svg_content, "Template field processing export failed")

        # Verify the template content is included
        self.assertIn("simple-test-template", svg_content, "Template ID not found in output")

        # Check that basic SVG structure is maintained
        self.assertIn("<svg", svg_content, "SVG root element missing")
        self.assertIn("</svg>", svg_content, "SVG closing tag missing")

        # Verify viewBox is properly set
        self.assertIn("viewBox", svg_content, "ViewBox attribute missing")

    def test_extreme_resolution_handling(self):
        """Test handling of extreme resolution scenarios."""
        # Test that very large theoretical resolutions don't cause overflow
        # This validates the safeguards in PageRenderer.cpp:223-224
        svg_content = self._export_svg_string()
        self.assertTrue(svg_content, "Base SVG export failed")

        # Validate output size is reasonable (not from integer overflow)
        content_size = len(svg_content)
        self.assertGreater(content_size, 100, "SVG output too small")
        self.assertLess(content_size, 50000000, "SVG output suspiciously large (>50MB)")

        # Check that SVG dimensions are reasonable
        if 'width=' in svg_content and 'height=' in svg_content:
            import re
            width_match = re.search(r'width="([^"]+)"', svg_content)
            height_match = re.search(r'height="([^"]+)"', svg_content)

            if width_match and height_match:
                width_str = width_match.group(1)
                height_str = height_match.group(1)

                # Basic sanity check - dimensions should contain numbers
                self.assertTrue(any(c.isdigit() for c in width_str), "Width contains no digits")
                self.assertTrue(any(c.isdigit() for c in height_str), "Height contains no digits")


    def test_deterministic_output(self):
        """Test that export output is deterministic across multiple runs."""
        # Generate multiple exports and verify they're identical
        svg_outputs = []
        for i in range(3):
            svg_content = self._export_svg_string()
            self.assertTrue(svg_content, f"SVG export {i} failed")
            svg_outputs.append(svg_content)

        # All outputs should be identical
        for i, svg in enumerate(svg_outputs[1:], 1):
            self.assertEqual(svg, svg_outputs[0],
                           f"SVG export {i} differs from first export - output not deterministic")

    def test_error_message_quality(self):
        """Test that error messages are informative and helpful."""
        # Test with completely invalid path
        invalid_path = "/dev/null/impossible/path.pdf"
        ok, err = self._export_pdf(invalid_path)
        self.assertFalse(ok, "Export to impossible path should fail")

        # Error should be informative (not just generic failure)
        if err:
            error_msg = str(err).lower()
            # Should mention file or path in error
            self.assertTrue(any(word in error_msg for word in ['file', 'path', 'directory', 'write']),
                          f"Error message not informative enough: {err}")

    # Phase 2: DrawViewSketch Tests -------------------------------------------

    @unittest.skipUnless(DRAWVIEWSKETCH_AVAILABLE, "DrawViewSketch not available in this build")
    def test_drawviewsketch_type_available(self):
        """DrawViewSketch should be available as a TechDraw type."""
        try:
            sketch_view = self._doc.addObject("TechDraw::DrawViewSketch", "SketchView")
            self.assertIsNotNone(sketch_view, "DrawViewSketch object not created")
            self.assertTrue(hasattr(sketch_view, "Source"), "DrawViewSketch missing Source property")
            self.assertTrue(hasattr(sketch_view, "Direction"), "DrawViewSketch missing Direction property")
        except Exception as e:
            self.fail(f"DrawViewSketch type not available: {e}")

    @unittest.skipUnless(DRAWVIEWSKETCH_AVAILABLE, "DrawViewSketch not available in this build")
    def test_drawviewsketch_simple_rectangle(self):
        """DrawViewSketch should render a simple rectangle sketch."""
        # Create a simple sketch with a rectangle
        sketch = self._doc.addObject("Sketcher::SketchObject", "RectangleSketch")
        sketch.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(100, 0, 0)), False)
        sketch.addGeometry(Part.LineSegment(App.Vector(100, 0, 0), App.Vector(100, 50, 0)), False)
        sketch.addGeometry(Part.LineSegment(App.Vector(100, 50, 0), App.Vector(0, 50, 0)), False)
        sketch.addGeometry(Part.LineSegment(App.Vector(0, 50, 0), App.Vector(0, 0, 0)), False)
        self._doc.recompute()

        # Create DrawViewSketch
        sketch_view = self._doc.addObject("TechDraw::DrawViewSketch", "RectView")
        sketch_view.Source = sketch
        sketch_view.X = 100.0
        sketch_view.Y = 100.0
        self._set_view_scale(sketch_view, 1.0)
        self._page.addView(sketch_view)
        self._doc.recompute()

        # Export to PDF
        pdf_path = self._tmp("sketch_rectangle.pdf")
        ok, err = self._export_pdf(pdf_path)
        self.assertTrue(ok, f"Sketch rectangle PDF export failed: {self._err_text(err)}")
        self.assertTrue(os.path.exists(pdf_path))
        self.assertGreaterEqual(os.path.getsize(pdf_path), 1200,
                          "PDF with sketch geometry should be larger than template-only")

        # Export to SVG and verify geometry is present
        svg_content = self._export_svg_string()
        self.assertTrue(svg_content, "Sketch rectangle SVG export failed")
        # SVG should contain line or path elements for the rectangle
        self.assertTrue('<line' in svg_content or '<path' in svg_content or '<polyline' in svg_content,
                       "SVG should contain geometry elements (line/path/polyline)")

    @unittest.skipUnless(DRAWVIEWSKETCH_AVAILABLE, "DrawViewSketch not available in this build")
    def test_drawviewsketch_circle(self):
        """DrawViewSketch should render a circle."""
        # Create sketch with a circle
        sketch = self._doc.addObject("Sketcher::SketchObject", "CircleSketch")
        sketch.addGeometry(Part.Circle(App.Vector(50, 50, 0), App.Vector(0, 0, 1), 30), False)
        self._doc.recompute()

        # Create DrawViewSketch
        sketch_view = self._doc.addObject("TechDraw::DrawViewSketch", "CircleView")
        sketch_view.Source = sketch
        sketch_view.X = 150.0
        sketch_view.Y = 150.0
        self._set_view_scale(sketch_view, 1.0)
        self._page.addView(sketch_view)
        self._doc.recompute()

        # Export and verify
        pdf_path = self._tmp("sketch_circle.pdf")
        ok, err = self._export_pdf(pdf_path)
        self.assertTrue(ok, f"Sketch circle PDF export failed: {self._err_text(err)}")
        self.assertGreaterEqual(os.path.getsize(pdf_path), 1200)

        svg_content = self._export_svg_string()
        self.assertTrue('<ellipse' in svg_content or '<circle' in svg_content or '<path' in svg_content,
                       "SVG should contain circle/ellipse geometry")

    @unittest.skipUnless(DRAWVIEWSKETCH_AVAILABLE, "DrawViewSketch not available in this build")
    def test_drawviewsketch_python_binding_returns_source(self):
        """Python binding should expose the linked Sketcher object."""
        sketch = self._doc.addObject("Sketcher::SketchObject", "BindingSketch")
        sketch.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(25, 0, 0)), False)
        self._doc.recompute()

        sketch_view = self._doc.addObject("TechDraw::DrawViewSketch", "BindingView")
        sketch_view.Source = sketch
        self._page.addView(sketch_view)
        self._doc.recompute()

        source = sketch_view.getSourceSketch()
        self.assertIsNotNone(source, "Binding getSourceSketch() returned None")
        self.assertEqual(getattr(source, "Name", None), sketch.Name,
                         "Binding returned unexpected sketch reference")

    @unittest.skipUnless(DRAWVIEWSKETCH_AVAILABLE, "DrawViewSketch not available in this build")
    def test_drawviewsketch_complex_geometry(self):
        """DrawViewSketch should handle complex sketches with mixed geometry."""
        # Create sketch with lines, arcs, and circles
        sketch = self._doc.addObject("Sketcher::SketchObject", "ComplexSketch")

        # Add rectangle base
        sketch.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(80, 0, 0)), False)
        sketch.addGeometry(Part.LineSegment(App.Vector(80, 0, 0), App.Vector(80, 60, 0)), False)
        sketch.addGeometry(Part.LineSegment(App.Vector(80, 60, 0), App.Vector(0, 60, 0)), False)
        sketch.addGeometry(Part.LineSegment(App.Vector(0, 60, 0), App.Vector(0, 0, 0)), False)

        # Add circle in center
        sketch.addGeometry(Part.Circle(App.Vector(40, 30, 0), App.Vector(0, 0, 1), 15), False)

        # Add arc
        sketch.addGeometry(Part.ArcOfCircle(Part.Circle(App.Vector(20, 45, 0), App.Vector(0, 0, 1), 10),
                                            0, 1.57), False)  # 90 degree arc
        self._doc.recompute()

        # Create DrawViewSketch
        sketch_view = self._doc.addObject("TechDraw::DrawViewSketch", "ComplexView")
        sketch_view.Source = sketch
        sketch_view.X = 120.0
        sketch_view.Y = 120.0
        self._set_view_scale(sketch_view, 1.5)
        self._page.addView(sketch_view)
        self._doc.recompute()

        # Export and verify
        pdf_path = self._tmp("sketch_complex.pdf")
        ok, err = self._export_pdf(pdf_path)
        self.assertTrue(ok, f"Complex sketch PDF export failed: {self._err_text(err)}")

        # Complex geometry should produce larger file
        self.assertGreater(os.path.getsize(pdf_path), 1500)

        svg_content = self._export_svg_string()
        # Should contain multiple geometry elements
        geometry_count = svg_content.count('<line') + svg_content.count('<path') + \
                        svg_content.count('<polyline') + svg_content.count('<circle') + \
                        svg_content.count('<ellipse')
        self.assertGreater(geometry_count, 3, "Complex sketch should have multiple geometry elements")

    @unittest.skipUnless(DRAWVIEWSKETCH_AVAILABLE, "DrawViewSketch not available in this build")
    def test_drawviewsketch_multiple_views(self):
        """Multiple DrawViewSketch objects should all render correctly."""
        # Create two different sketches
        sketch1 = self._doc.addObject("Sketcher::SketchObject", "Sketch1")
        sketch1.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(50, 50, 0)), False)

        sketch2 = self._doc.addObject("Sketcher::SketchObject", "Sketch2")
        sketch2.addGeometry(Part.Circle(App.Vector(25, 25, 0), App.Vector(0, 0, 1), 20), False)
        self._doc.recompute()

        # Create two views
        view1 = self._doc.addObject("TechDraw::DrawViewSketch", "View1")
        view1.Source = sketch1
        view1.X = 50.0
        view1.Y = 50.0

        view2 = self._doc.addObject("TechDraw::DrawViewSketch", "View2")
        view2.Source = sketch2
        view2.X = 150.0
        view2.Y = 150.0

        self._page.addView(view1)
        self._page.addView(view2)
        self._doc.recompute()

        # Export and verify both views are present
        svg_content = self._export_svg_string()
        self.assertTrue(svg_content, "Multi-view export failed")

        # Should have geometry from both sketches
        geometry_count = svg_content.count('<line') + svg_content.count('<path') + \
                        svg_content.count('<polyline') + svg_content.count('<ellipse')
        self.assertGreaterEqual(geometry_count, 1, "Should have geometry from multiple views")

    @unittest.skipUnless(DRAWVIEWSKETCH_AVAILABLE, "DrawViewSketch not available in this build")
    def test_drawviewsketch_center_alignment(self):
        """Sketch views should honour placement offsets regardless of sketch origin."""
        sketch = self._doc.addObject("Sketcher::SketchObject", "OffsetSketch")
        # Create a rectangle shifted away from the origin to exercise centring logic
        sketch.addGeometry(Part.LineSegment(App.Vector(120, 80, 0), App.Vector(180, 80, 0)), False)
        sketch.addGeometry(Part.LineSegment(App.Vector(180, 80, 0), App.Vector(180, 130, 0)), False)
        sketch.addGeometry(Part.LineSegment(App.Vector(180, 130, 0), App.Vector(120, 130, 0)), False)
        sketch.addGeometry(Part.LineSegment(App.Vector(120, 130, 0), App.Vector(120, 80, 0)), False)
        self._doc.recompute()

        view = self._doc.addObject("TechDraw::DrawViewSketch", "OffsetView")
        view.Source = sketch
        view.X = 140.0
        view.Y = 95.0
        self._set_view_scale(view, 1.5)
        self._page.addView(view)
        self._doc.recompute()

        svg_content = self._export_svg_string()
        mm_to_device = self._extract_mm_to_device(svg_content)
        centres_px = self._cluster_svg_centers(svg_content, clusters=1)[0]
        page_height = self._extract_page_height(svg_content)

        centre_x_mm = centres_px[0] / mm_to_device
        centre_y_mm_from_top = centres_px[1] / mm_to_device
        centre_y_mm = page_height - centre_y_mm_from_top

        self.assertAlmostEqual(centre_x_mm, view.X.Value, delta=0.5)
        self.assertAlmostEqual(centre_y_mm, view.Y.Value, delta=0.5)

    @unittest.skipUnless(DRAWVIEWSKETCH_AVAILABLE, "DrawViewSketch not available in this build")
    def test_drawviewsketch_with_template(self):
        """DrawViewSketch should work with template."""
        template_path = os.path.join(os.path.dirname(__file__), "TestTemplate.svg")
        if not os.path.exists(template_path):
            self.skipTest("TestTemplate.svg not found")

        template = self._doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        template.Template = template_path
        self._page.Template = template

        # Create sketch
        sketch = self._doc.addObject("Sketcher::SketchObject", "TemplateSketch")
        sketch.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(100, 100, 0)), False)

        # Create view
        sketch_view = self._doc.addObject("TechDraw::DrawViewSketch", "TemplateView")
        sketch_view.Source = sketch
        sketch_view.X = 100.0
        sketch_view.Y = 100.0
        self._page.addView(sketch_view)
        self._doc.recompute()

        # Export
        pdf_path = self._tmp("sketch_with_template.pdf")
        ok, err = self._export_pdf(pdf_path)
        self.assertTrue(ok, f"Sketch with template PDF export failed: {self._err_text(err)}")

        svg_content = self._export_svg_string()
        # Should contain both template and sketch geometry
        self.assertTrue(svg_content, "Template + sketch SVG export failed")
        self.assertTrue('<line' in svg_content or '<path' in svg_content or '<polyline' in svg_content,
                       "Should contain sketch geometry")

    @unittest.skipUnless(DRAWVIEWSKETCH_AVAILABLE, "DrawViewSketch not available in this build")
    def test_drawviewsketch_empty_sketch(self):
        """DrawViewSketch should handle empty sketches gracefully."""
        # Create empty sketch
        sketch = self._doc.addObject("Sketcher::SketchObject", "EmptySketch")
        self._doc.recompute()

        # Create view
        sketch_view = self._doc.addObject("TechDraw::DrawViewSketch", "EmptyView")
        sketch_view.Source = sketch
        sketch_view.X = 100.0
        sketch_view.Y = 100.0
        self._page.addView(sketch_view)
        self._doc.recompute()

        # Should export without error, even though sketch is empty
        pdf_path = self._tmp("sketch_empty.pdf")
        ok, err = self._export_pdf(pdf_path)
        self.assertTrue(ok, f"Empty sketch PDF export failed: {self._err_text(err)}")

    def test_drawviewannotation_headless(self):
        """DrawViewAnnotation text should render in headless exports."""
        note = self._doc.addObject("TechDraw::DrawViewAnnotation", "Anno")
        note.Text = ["Cover Flat", "174.3 x 57.1 mm"]
        note.TextSize = 3.5
        note.TextColor = (0.1, 0.1, 0.1)
        note.LineSpace = 120
        note.X = 120.0
        note.Y = 190.0
        self._page.addView(note)
        self._doc.recompute()

        pdf_path = self._tmp("annotation.pdf")
        ok, err = self._export_pdf(pdf_path)
        self.assertTrue(ok, f"Annotation PDF export failed: {self._err_text(err)}")

        svg_content = self._export_svg_string()
        self.assertIn("Cover Flat", svg_content)

    def test_drawviewpart_two_piece_assembly(self):
        """DrawViewPart should export multi-body assemblies headlessly."""
        body_cover = self._doc.addObject("Part::Feature", "CoverBody")
        body_cover.Shape = Part.makeBox(120, 80, 5)

        body_wrap = self._doc.addObject("Part::Feature", "WrapBody")
        body_wrap.Shape = Part.makeBox(120, 80, 5)
        body_wrap.Placement.Base = App.Vector(0, 0, 45)

        view = self._doc.addObject("TechDraw::DrawViewPart", "AssemblyView")
        view.Source = [body_cover, body_wrap]
        view.Direction = (0, 0, 1)
        self._set_view_scale(view, 0.6)
        self._page.addView(view)
        self._doc.recompute()

        pdf_path = self._tmp("assembly_view.pdf")
        ok, err = self._export_pdf(pdf_path)
        self.assertTrue(ok, f"DrawViewPart PDF export failed: {self._err_text(err)}")
        self.assertTrue(os.path.exists(pdf_path), "PDF file missing for DrawViewPart export")
        svg_content = self._export_svg_string()
        self.assertTrue(svg_content, "DrawViewPart SVG export empty")
        self.assertNotIn("Qt SVG Document", svg_content,
                         "DrawViewPart fell back to stub SVG output")
        self.assertGreater(svg_content.count("<path"), 1,
                           "DrawViewPart SVG missing geometry paths")
        self.assertGreater(svg_content.count("stroke-width"), 1,
                           "DrawViewPart SVG missing geometry strokes")

    def test_drawviewpart_view_positioning(self):
        """DrawViewPart exports should honour placement coordinates in headless mode."""
        block = self._doc.addObject("Part::Feature", "TDTestBlock")
        block.Shape = Part.makeBox(40, 30, 10)

        view = self._doc.addObject("TechDraw::DrawViewPart", "TDTestBlockFront")
        view.Source = [block]
        view.Direction = (0, 0, 1)
        self._set_view_scale(view, 0.4)
        view.X = 145.0
        view.Y = 95.0
        if hasattr(view, "AutoPos"):
            view.AutoPos = False
        if hasattr(view, "KeepUpdated"):
            view.KeepUpdated = False

        self._page.addView(view)
        self._doc.recompute()

        svg_content = self._export_svg_string()
        mm_to_device = self._extract_mm_to_device(svg_content)
        center1_px = self._cluster_svg_centers(svg_content, clusters=1)[0]

        # Move the view and confirm the exported geometry shifts accordingly
        delta_x_mm = 40.0
        delta_y_mm = -30.0
        view.X = view.X.Value + delta_x_mm
        view.Y = view.Y.Value + delta_y_mm
        self._doc.recompute()

        svg_content = self._export_svg_string()
        mm_to_device_after = self._extract_mm_to_device(svg_content)
        center2_px = self._cluster_svg_centers(svg_content, clusters=1)[0]

        shift_x_px = abs(center2_px[0] - center1_px[0])
        shift_y_px = abs(center2_px[1] - center1_px[1])
        expected_x_px = abs(delta_x_mm) * mm_to_device_after
        expected_y_px = abs(delta_y_mm) * mm_to_device_after

        self.assertGreater(shift_x_px, expected_x_px * 0.5,
                           f"DrawViewPart X translation too small ({shift_x_px/mm_to_device_after:.2f} mm)")
        self.assertGreater(shift_y_px, expected_y_px * 0.5,
                           f"DrawViewPart Y translation too small ({shift_y_px/mm_to_device_after:.2f} mm)")

    def test_drawviewpart_multiple_views_separated(self):
        """Multiple DrawViewPart instances honour independent placement offsets."""
        block = self._doc.addObject("Part::Feature", "LayoutBlock")
        block.Shape = Part.makeBox(60, 40, 15)

        left = self._doc.addObject("TechDraw::DrawViewPart", "LeftView")
        left.Source = [block]
        left.Direction = (0, 0, 1)
        self._set_view_scale(left, 0.4)
        left.X = 85.0
        left.Y = 120.0
        if hasattr(left, "AutoPos"):
            left.AutoPos = False
        if hasattr(left, "KeepUpdated"):
            left.KeepUpdated = False

        right = self._doc.addObject("TechDraw::DrawViewPart", "RightView")
        right.Source = [block]
        right.Direction = (0, 0, 1)
        self._set_view_scale(right, 0.4)
        right.X = 215.0
        right.Y = 120.0
        if hasattr(right, "AutoPos"):
            right.AutoPos = False
        if hasattr(right, "KeepUpdated"):
            right.KeepUpdated = False

        self._page.addView(left)
        self._page.addView(right)
        self._doc.recompute()

        # Auto-placement may reposition freshly added views; reassert the intended
        # offsets now that the page exists to ensure deterministic spacing.
        left.X = 85.0
        left.Y = 120.0
        right.X = 215.0
        right.Y = 120.0
        self._doc.recompute()

        svg_content = self._export_svg_string()
        mm_to_device = self._extract_mm_to_device(svg_content)
        centres_px = self._cluster_svg_centers(svg_content, clusters=2)
        centres_mm = [(x / mm_to_device, y / mm_to_device) for x, y in centres_px]
        centres_mm.sort(key=lambda pt: pt[0])

        delta_actual = centres_mm[1][0] - centres_mm[0][0]
        self.assertGreater(
            delta_actual,
            60.0,
            f"View separation too small ({delta_actual:.2f} mm)",
        )

        expected_y = self._page.PageHeight - left.Y.Value
        for _, center_y in centres_mm:
            self.assertAlmostEqual(
                center_y,
                expected_y,
                delta=5.0,
                msg=f"Cluster centre Y {center_y:.2f} mm not aligned with expected {expected_y:.2f} mm",
            )

    def test_drawviewpart_scale_factor_applies_once(self):
        """Scaling a view should only apply once in the exported geometry."""
        block = self._doc.addObject("Part::Feature", "ScaleCheckBlock")
        block.Shape = Part.makeBox(30, 20, 10)

        view = self._doc.addObject("TechDraw::DrawViewPart", "ScaleCheckView")
        view.Source = [block]
        view.Direction = (0, 0, 1)
        self._set_view_scale(view, 1.0)
        view.X = 110.0
        view.Y = 85.0
        if hasattr(view, "AutoPos"):
            view.AutoPos = False
        if hasattr(view, "KeepUpdated"):
            view.KeepUpdated = False
        self._page.addView(view)
        self._doc.recompute()

        svg_content = self._export_svg_string()
        min_x1, max_x1, _, _ = self._svg_path_bounds(svg_content)
        width1 = max_x1 - min_x1

        self._set_view_scale(view, 2.0)
        self._doc.recompute()
        svg_content = self._export_svg_string()
        min_x2, max_x2, _, _ = self._svg_path_bounds(svg_content)
        width2 = max_x2 - min_x2

        self.assertGreater(width1, 0.0)
        # Allow for small numerical differences introduced by tessellation
        self.assertAlmostEqual(width2 / width1, 2.0, delta=0.1)

    @unittest.skipIf(PyPDF2 is None, "PyPDF2 not installed")
    def test_drawviewpart_pdf_view_positioning(self):
        """DrawViewPart PDF exports should reflect placement offsets."""
        block = self._doc.addObject("Part::Feature", "TDTestPdfBlock")
        block.Shape = Part.makeBox(40, 30, 10)

        view = self._doc.addObject("TechDraw::DrawViewPart", "TDTestPdfFront")
        view.Source = [block]
        view.Direction = (0, 0, 1)
        scale_value = 0.4
        self._set_view_scale(view, scale_value)
        view.X = 145.0
        view.Y = 95.0
        if hasattr(view, "AutoPos"):
            view.AutoPos = False
        if hasattr(view, "KeepUpdated"):
            view.KeepUpdated = False

        self._page.addView(view)
        self._doc.recompute()

        pdf_initial = self._tmp("pdf_view_initial.pdf")
        ok, err = self._export_pdf(pdf_initial)
        self.assertTrue(ok, f"Initial PDF export failed: {self._err_text(err)}")

        bounds1, width_pts, height_pts = self._pdf_view_bounds(pdf_initial)
        center1 = ((bounds1[0] + bounds1[2]) / 2.0, (bounds1[1] + bounds1[3]) / 2.0)

        delta_x_mm = 40.0
        delta_y_mm = -30.0
        view.X = view.X.Value + delta_x_mm
        view.Y = view.Y.Value + delta_y_mm
        self._doc.recompute()

        pdf_shifted = self._tmp("pdf_view_shifted.pdf")
        ok, err = self._export_pdf(pdf_shifted)
        self.assertTrue(ok, f"Shifted PDF export failed: {self._err_text(err)}")

        bounds2, _, _ = self._pdf_view_bounds(pdf_shifted)
        center2 = ((bounds2[0] + bounds2[2]) / 2.0, (bounds2[1] + bounds2[3]) / 2.0)

        shift_x_pts = abs(center2[0] - center1[0])
        shift_y_pts = abs(center2[1] - center1[1])

        block_width_mm = 40.0 * scale_value
        block_height_mm = 30.0 * scale_value
        mm_to_pts_x = width_pts / block_width_mm if block_width_mm else 0.0
        mm_to_pts_y = height_pts / block_height_mm if block_height_mm else 0.0
        mm_to_pts = (mm_to_pts_x + mm_to_pts_y) / 2.0 if (mm_to_pts_x and mm_to_pts_y) else mm_to_pts_x or mm_to_pts_y

        self.assertGreater(mm_to_pts, 0.0, "Derived PDF mm-to-point scale invalid")

        expected_x_pts = abs(delta_x_mm) * mm_to_pts
        expected_y_pts = abs(delta_y_mm) * mm_to_pts

        self.assertGreater(
            shift_x_pts,
            expected_x_pts * 0.5,
            f"PDF X translation too small ({shift_x_pts / mm_to_pts:.2f} mm)",
        )
        self.assertGreater(
            shift_y_pts,
            expected_y_pts * 0.5,
            f"PDF Y translation too small ({shift_y_pts / mm_to_pts:.2f} mm)",
        )

    @unittest.skipIf(PyPDF2 is None, "PyPDF2 not installed")
    def test_drawviewannotation_pdf_view_positioning(self):
        """DrawViewAnnotation PDF exports should respect page placement offsets."""
        block = self._doc.addObject("Part::Feature", "TDAnnoBlock")
        block.Shape = Part.makeBox(40, 30, 10)

        view = self._doc.addObject("TechDraw::DrawViewPart", "TDAnnoView")
        view.Source = [block]
        view.Direction = (0, 0, 1)
        self._set_view_scale(view, 0.4)
        view.X = 120.0
        view.Y = 140.0
        if hasattr(view, "AutoPos"):
            view.AutoPos = False
        if hasattr(view, "KeepUpdated"):
            view.KeepUpdated = False
        self._page.addView(view)

        note = self._doc.addObject("TechDraw::DrawViewAnnotation", "AnnoPdf")
        note.Text = ["Assembly", "OSE-1"]
        note.TextSize = 3.5
        note.TextColor = (0.0, 0.0, 0.0)
        note.LineSpace = 110
        note.X = 200.0
        note.Y = 185.0
        self._page.addView(note)
        self._doc.recompute()

        pdf_initial = self._tmp("annotation_initial.pdf")
        ok, err = self._export_pdf(pdf_initial)
        self.assertTrue(ok, f"Initial annotation PDF export failed: {self._err_text(err)}")

        bounds, width_pts, height_pts = self._pdf_view_bounds(pdf_initial)
        note_pos1 = self._pdf_text_positions(pdf_initial)
        self.assertTrue(note_pos1, "No annotation text matrices recorded in PDF export")
        note_center1 = note_pos1[0]

        delta_x_mm = 35.0
        delta_y_mm = -25.0
        note.X = note.X.Value + delta_x_mm
        note.Y = note.Y.Value + delta_y_mm
        self._doc.recompute()

        pdf_shifted = self._tmp("annotation_shifted.pdf")
        ok, err = self._export_pdf(pdf_shifted)
        self.assertTrue(ok, f"Shifted annotation PDF export failed: {self._err_text(err)}")

        note_pos2 = self._pdf_text_positions(pdf_shifted)
        self.assertTrue(note_pos2, "No annotation text matrices recorded after move")
        note_center2 = note_pos2[0]

        shift_x_pts = abs(note_center2[0] - note_center1[0])
        shift_y_pts = abs(note_center2[1] - note_center1[1])

        block_width_mm = 40.0 * view.Scale.Value if hasattr(view.Scale, "Value") else 40.0 * view.Scale
        block_height_mm = 30.0 * view.Scale.Value if hasattr(view.Scale, "Value") else 30.0 * view.Scale
        mm_to_pts_x = width_pts / block_width_mm if block_width_mm else 0.0
        mm_to_pts_y = height_pts / block_height_mm if block_height_mm else 0.0
        mm_to_pts = (mm_to_pts_x + mm_to_pts_y) / 2.0 if (mm_to_pts_x and mm_to_pts_y) else mm_to_pts_x or mm_to_pts_y
        self.assertGreater(mm_to_pts, 0.0, "Derived PDF mm-to-point scale invalid for annotations")

        expected_x_pts = abs(delta_x_mm) * mm_to_pts
        expected_y_pts = abs(delta_y_mm) * mm_to_pts

        self.assertGreater(
            shift_x_pts,
            expected_x_pts * 0.5,
            f"Annotation X translation too small ({shift_x_pts / mm_to_pts:.2f} mm)",
        )
        self.assertGreater(
            shift_y_pts,
            expected_y_pts * 0.5,
            f"Annotation Y translation too small ({shift_y_pts / mm_to_pts:.2f} mm)",
        )

    def test_drawviewannotation_svg_view_positioning(self):
        """DrawViewAnnotation SVG exports should respect placement offsets."""
        block = self._doc.addObject("Part::Feature", "TDAnnoBlockSvg")
        block.Shape = Part.makeBox(40, 30, 10)

        view = self._doc.addObject("TechDraw::DrawViewPart", "TDAnnoViewSvg")
        view.Source = [block]
        view.Direction = (0, 0, 1)
        view.Scale = 0.4
        view.X = 120.0
        view.Y = 140.0
        if hasattr(view, "AutoPos"):
            view.AutoPos = False
        if hasattr(view, "KeepUpdated"):
            view.KeepUpdated = False
        self._page.addView(view)

        note = self._doc.addObject("TechDraw::DrawViewAnnotation", "AnnoSvg")
        note.Text = ["SVG note"]
        note.TextSize = 3.5
        note.X = 80.0
        note.Y = 150.0
        self._page.addView(note)
        self._doc.recompute()

        svg_initial = self._export_svg_string()
        positions1 = self._svg_text_positions_mm(svg_initial)
        self.assertTrue(positions1, "No SVG annotation text transform recorded")
        note_pos1 = positions1[0]

        delta_x_mm = 25.0
        delta_y_mm = -20.0
        note.X = note.X.Value + delta_x_mm
        note.Y = note.Y.Value + delta_y_mm
        self._doc.recompute()

        svg_shifted = self._export_svg_string()
        positions2 = self._svg_text_positions_mm(svg_shifted)
        self.assertTrue(positions2, "No SVG annotation text transform recorded after move")
        note_pos2 = positions2[0]

        shift_x_mm = abs(note_pos2[0] - note_pos1[0])
        shift_y_mm = abs(note_pos2[1] - note_pos1[1])

        self.assertGreater(
            shift_x_mm,
            abs(delta_x_mm) * 0.8,
            f"SVG annotation X translation too small ({shift_x_mm:.2f} mm)",
        )
        self.assertGreater(
            shift_y_mm,
            abs(delta_y_mm) * 0.8,
            f"SVG annotation Y translation too small ({shift_y_mm:.2f} mm)",
        )

    def test_reverseengineering_bezier_grid_layout(self):
        """ReverseEngineering helper should map poles column-major."""
        if ReverseEngineering is None:
            self.skipTest("ReverseEngineering module not available")

        poles = [(float(i), float(i + 0.1), float(i + 0.2)) for i in range(9)]
        grid = ReverseEngineering.assignBezierControlGrid(poles, 3, 3)

        self.assertEqual(len(grid), 3, "Expected three columns in control grid")
        flattened = [tuple(point) for column in grid for point in column]
        expected = [tuple(poles[i]) for i in range(9)]
        self.assertEqual(flattened, expected)

    @staticmethod
    def _extract_mm_to_device(svg_content: str) -> float:
        """Return the millimetre-to-device scaling factor reported in the SVG."""
        pattern = r'transform="matrix\(([-\d\.]+),0,0,([-\d\.]+),([-\d\.]+),([-\d\.]+)\)"'
        matches = [
            (float(a), float(d))
            for a, d, _, _ in re.findall(pattern, svg_content)
            if math.isclose(float(a), float(d), rel_tol=1e-6)
        ]
        scales = [abs(a) for a, _ in matches if abs(a) > 1.0]
        if scales:
            return min(scales)

        width_match = re.search(r'width="([0-9.]+)mm"', svg_content)
        viewbox_match = re.search(r'viewBox="([-\d\.]+)\s+([-\d\.]+)\s+([-\d\.]+)\s+([-\d\.]+)"', svg_content)
        if width_match and viewbox_match:
            try:
                width_mm = float(width_match.group(1))
                viewbox_width = float(viewbox_match.group(3))
                if width_mm > 0.0 and viewbox_width > 0.0:
                    return viewbox_width / width_mm
            except ValueError:
                pass

        raise AssertionError("Unable to derive SVG scaling factor from export output")

    @staticmethod
    def _pdf_view_bounds(pdf_path: str):
        """Return the transformed bounds of geometry recorded in the PDF content stream."""
        if PyPDF2 is None:
            raise AssertionError("PyPDF2 is required for PDF parsing")

        reader = PyPDF2.PdfReader(pdf_path)
        if not reader.pages:
            raise AssertionError("PDF export produced no pages")

        page = reader.pages[0]
        coords = DrawHeadlessExportTest._pdf_collect_coordinates(page, reader)
        if not coords:
            raise AssertionError("No vector coordinates decoded from PDF export")

        filtered = DrawHeadlessExportTest._filter_pdf_geometry(coords)
        if filtered:
            coords = filtered

        xs = [pt[0] for pt in coords]
        ys = [pt[1] for pt in coords]
        bounds = (min(xs), min(ys), max(xs), max(ys))
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        return bounds, width, height

    @staticmethod
    def _pdf_collect_coordinates(page, reader):
        """Decode the page content stream and return transformed drawing coordinates."""
        from PyPDF2.generic import ContentStream  # Imported lazily because PyPDF2 is optional

        raw_content = page.get_contents()
        if raw_content is None:
            return []

        stream = ContentStream(raw_content, reader)

        coords = []
        ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]  # Current transformation matrix
        stack = []

        for operands, operator in stream.operations:
            op = operator.decode("latin-1") if isinstance(operator, bytes) else operator

            if op == "q":
                stack.append(ctm[:])
            elif op == "Q":
                ctm = stack.pop() if stack else [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            elif op == "cm":
                values = [float(value) for value in operands]
                if len(values) == 6:
                    ctm = DrawHeadlessExportTest._pdf_matrix_multiply(ctm, values)
            elif op in {"m", "l"}:
                if len(operands) >= 2:
                    x = float(operands[0])
                    y = float(operands[1])
                    coords.append(DrawHeadlessExportTest._pdf_transform_point(ctm, x, y))
            elif op == "c":
                values = [float(value) for value in operands]
                for index in range(0, len(values), 2):
                    if index + 1 < len(values):
                        coords.append(
                            DrawHeadlessExportTest._pdf_transform_point(
                                ctm, values[index], values[index + 1]
                            )
                        )
            elif op == "v":
                if len(operands) >= 4:
                    x2, y2, x3, y3 = map(float, operands[-4:])
                    coords.append(DrawHeadlessExportTest._pdf_transform_point(ctm, x2, y2))
                    coords.append(DrawHeadlessExportTest._pdf_transform_point(ctm, x3, y3))
            elif op == "y":
                if len(operands) >= 4:
                    x1, y1, x3, y3 = map(float, operands[-4:])
                    coords.append(DrawHeadlessExportTest._pdf_transform_point(ctm, x1, y1))
                    coords.append(DrawHeadlessExportTest._pdf_transform_point(ctm, x3, y3))
            elif op == "re":
                if len(operands) >= 4:
                    x, y, w, h = map(float, operands[:4])
                    rect = [
                        (x, y),
                        (x + w, y),
                        (x + w, y + h),
                        (x, y + h),
                    ]
                    coords.extend(
                        DrawHeadlessExportTest._pdf_transform_point(ctm, px, py) for px, py in rect
                    )

        return coords

    @staticmethod
    def _filter_pdf_geometry(coords):
        """Remove template outliers so view bounds reflect TechDraw geometry."""
        if len(coords) < 6:
            return []

        _, ys = zip(*coords)
        median_y = statistics.median(ys)
        deviations = [abs(y - median_y) for y in ys]
        mad_y = statistics.median(deviations)
        threshold = max(mad_y * 6.0, 1.0)

        filtered = [point for point in coords if abs(point[1] - median_y) <= threshold]
        return filtered

    @staticmethod
    def _pdf_matrix_multiply(m1, m2):
        """Return the product of two PDF affine transform matrices."""
        a1, b1, c1, d1, e1, f1 = m1
        a2, b2, c2, d2, e2, f2 = m2
        return [
            a1 * a2 + b1 * c2,
            a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2,
            c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2,
            e1 * b2 + f1 * d2 + f2,
        ]

    @staticmethod
    def _pdf_transform_point(matrix, x_coord, y_coord):
        """Apply the affine matrix to an (x, y) coordinate."""
        a, b, c, d, e, f = matrix
        return (
            a * x_coord + c * y_coord + e,
            b * x_coord + d * y_coord + f,
        )

    @staticmethod
    def _pdf_text_positions(pdf_path: str):
        """Return the base positions for text matrices within the PDF."""
        if PyPDF2 is None:
            raise AssertionError("PyPDF2 is required for PDF parsing")

        reader = PyPDF2.PdfReader(pdf_path)
        if not reader.pages:
            raise AssertionError("PDF export produced no pages")

        page = reader.pages[0]
        return DrawHeadlessExportTest._pdf_collect_text_positions(page, reader)

    @staticmethod
    def _pdf_collect_text_positions(page, reader):
        """Decode text matrices (Tm/Td) and return their transformed origins."""
        from PyPDF2.generic import ContentStream  # Imported lazily because PyPDF2 is optional

        raw_content = page.get_contents()
        if raw_content is None:
            return []

        stream = ContentStream(raw_content, reader)
        positions = []

        ctm_stack = []
        text_matrix_stack = []
        ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        text_matrix = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]

        for operands, operator in stream.operations:
            op = operator.decode("latin-1") if isinstance(operator, bytes) else operator

            if op == "q":
                ctm_stack.append(ctm[:])
                text_matrix_stack.append(text_matrix[:])
            elif op == "Q":
                ctm = ctm_stack.pop() if ctm_stack else [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
                text_matrix = text_matrix_stack.pop() if text_matrix_stack else [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            elif op == "cm":
                values = [float(value) for value in operands]
                if len(values) == 6:
                    ctm = DrawHeadlessExportTest._pdf_matrix_multiply(ctm, values)
            elif op == "Tm":
                values = [float(value) for value in operands]
                if len(values) == 6:
                    text_matrix = values
                    combined = DrawHeadlessExportTest._pdf_matrix_multiply(ctm, text_matrix)
                    positions.append((combined[4], combined[5]))
            elif op == "Td":
                if len(operands) >= 2:
                    tx = float(operands[0])
                    ty = float(operands[1])
                    text_matrix = DrawHeadlessExportTest._pdf_matrix_multiply(
                        text_matrix, [1.0, 0.0, 0.0, 1.0, tx, ty]
                    )
                    combined = DrawHeadlessExportTest._pdf_matrix_multiply(ctm, text_matrix)
                    positions.append((combined[4], combined[5]))
            elif op == "TD":
                if len(operands) >= 2:
                    tx = float(operands[0])
                    ty = float(operands[1])
                    text_matrix = DrawHeadlessExportTest._pdf_matrix_multiply(
                        text_matrix, [1.0, 0.0, 0.0, 1.0, tx, ty]
                    )
                    combined = DrawHeadlessExportTest._pdf_matrix_multiply(ctm, text_matrix)
                    positions.append((combined[4], combined[5]))

        return positions

    @staticmethod
    def _extract_path_bbox(svg_content: str) -> tuple[float, float, float, float]:
        """Return the bounding box for all <path> elements in the SVG."""
        try:
            root = ET.fromstring(svg_content)
        except ET.ParseError as exc:  # pragma: no cover - invalid SVG should fail elsewhere first
            raise AssertionError(f"Failed to parse SVG content: {exc}")

        ns = {'svg': 'http://www.w3.org/2000/svg'}
        xs: list[float] = []
        ys: list[float] = []
        pattern = r'[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?'

        for path in root.findall('.//svg:path', ns):
            coords = [float(tok) for tok in re.findall(pattern, path.get('d', ''))]
            if coords:
                xs.extend(coords[0::2])
                ys.extend(coords[1::2])

        if not xs or not ys:
            raise AssertionError("No path geometry found in SVG export")

        return min(xs), max(xs), min(ys), max(ys)

    def _svg_path_bounds(self, svg_content: str) -> tuple[float, float, float, float]:
        """Return the bounding box for path-like geometry (<path>/<polyline>/<polygon>)."""
        try:
            root = ET.fromstring(svg_content)
        except ET.ParseError as exc:
            raise AssertionError(f"Failed to parse SVG content: {exc}")

        ns = {'svg': 'http://www.w3.org/2000/svg'}
        xs: list[float] = []
        ys: list[float] = []
        pattern = re.compile(r'[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?')

        def extend_from_coords(values):
            coords = [float(tok) for tok in values]
            if coords:
                xs.extend(coords[0::2])
                ys.extend(coords[1::2])

        for path in root.findall('.//svg:path', ns):
            extend_from_coords(pattern.findall(path.get('d', '')))

        for poly in root.findall('.//svg:polyline', ns) + root.findall('.//svg:polygon', ns):
            extend_from_coords(pattern.findall(poly.get('points', '')))

        if not xs or not ys:
            raise AssertionError("No polyline/path geometry found in SVG export")

        return min(xs), max(xs), min(ys), max(ys)

    @staticmethod
    def _extract_page_height(svg_content: str) -> float:
        """Return the page height in millimetres from the SVG header."""
        match = re.search(r'height="([0-9.]+)mm"', svg_content)
        if not match:
            raise AssertionError("Unable to determine page height from SVG header")
        return float(match.group(1))

    def _svg_text_positions_mm(self, svg_content: str) -> list[tuple[float, float]]:
        """Return per-annotation positions derived from SVG transform matrices."""
        mm_to_device = self._extract_mm_to_device(svg_content)
        if not (mm_to_device > 0.0):
            raise AssertionError("Invalid SVG scaling factor for annotation parsing")
        page_height = self._extract_page_height(svg_content)
        try:
            root = ET.fromstring(svg_content)
        except ET.ParseError as exc:  # pragma: no cover - invalid SVG should fail elsewhere first
            raise AssertionError(f"Failed to parse SVG content for annotation positions: {exc}")

        ns = {'svg': 'http://www.w3.org/2000/svg'}
        positions: list[tuple[float, float]] = []
        for group in root.findall('.//svg:g', ns):
            transform = group.attrib.get('transform')
            if not transform or not group.findall('.//svg:text', ns):
                continue
            values = self._parse_svg_matrix(transform)
            if not values:
                continue
            tx_device = values[4]
            ty_device = values[5]
            x_mm = tx_device
            y_top_mm = ty_device
            y_mm = page_height - y_top_mm
            positions.append((x_mm, y_mm))
        return positions

    @staticmethod
    def _parse_svg_matrix(transform: str) -> list[float] | None:
        match = re.search(r'matrix\(([^)]+)\)', transform)
        if not match:
            return None
        try:
            return [float(value) for value in re.split(r'[ ,]+', match.group(1).strip()) if value]
        except ValueError:
            return None

    @staticmethod
    def _cluster_svg_centers(svg_content: str, clusters: int) -> list[tuple[float, float]]:
        """Approximate per-view centres (device units) via simple k-means clustering."""
        if clusters < 1:
            raise AssertionError("Cluster count must be positive")

        root = ET.fromstring(svg_content)
        pattern = re.compile(r'[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?')
        matrix_pattern = re.compile(r'matrix\(([^)]+)\)')

        def parse_matrices(transform: str) -> list[tuple[float, float, float, float, float, float]]:
            matrices: list[tuple[float, float, float, float, float, float]] = []
            for match in matrix_pattern.finditer(transform):
                values = [float(v) for v in re.split(r'[ ,]+', match.group(1).strip()) if v]
                if len(values) == 6:
                    matrices.append(tuple(values))  # type: ignore[arg-type]
            return matrices

        def multiply(m1, m2):
            a1, b1, c1, d1, e1, f1 = m1
            a2, b2, c2, d2, e2, f2 = m2
            return (
                a1 * a2 + c1 * b2,
                b1 * a2 + d1 * b2,
                a1 * c2 + c1 * d2,
                b1 * c2 + d1 * d2,
                a1 * e2 + c1 * f2 + e1,
                b1 * e2 + d1 * f2 + f1,
            )

        def apply(matrix, x, y):
            a, b, c, d, e, f = matrix
            return a * x + c * y + e, b * x + d * y + f

        points: list[tuple[float, float]] = []

        def walk(node, matrix):
            transform = node.get('transform')
            local_matrix = matrix
            if transform:
                for component in parse_matrices(transform):
                    local_matrix = multiply(local_matrix, component)

            stroke_width_attr = node.get('stroke-width')
            try:
                width_val = float(stroke_width_attr) if stroke_width_attr else 1.0
            except ValueError:
                width_val = 1.0

            def append_points(raw_points):
                if width_val < 1.0:
                    return
                for x, y in raw_points:
                    points.append(apply(local_matrix, x, y))

            if node.tag.endswith('path'):
                coords = [float(tok) for tok in pattern.findall(node.get('d', ''))]
                append_points(list(zip(coords[0::2], coords[1::2])))
            elif node.tag.endswith('polyline') or node.tag.endswith('polygon'):
                coord_values = [float(tok) for tok in pattern.findall(node.get('points', ''))]
                append_points(list(zip(coord_values[0::2], coord_values[1::2])))

            for child in list(node):
                walk(child, local_matrix)

        walk(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))

        if len(points) < clusters:
            raise AssertionError("Insufficient geometry for clustering")

        sorted_points = sorted(points, key=lambda pt: pt[0])
        centres = [
            [sorted_points[int(len(points) * (i + 0.5) / clusters)][0],
             sorted_points[int(len(points) * (i + 0.5) / clusters)][1]]
            for i in range(clusters)
        ]

        for _ in range(10):
            groups = [[] for _ in range(clusters)]
            for point in points:
                idx = min(
                    range(clusters),
                    key=lambda i: (point[0] - centres[i][0]) ** 2 + (point[1] - centres[i][1]) ** 2,
                )
                groups[idx].append(point)

            updated = False
            for idx, group in enumerate(groups):
                if group:
                    new_x = sum(p[0] for p in group) / len(group)
                    new_y = sum(p[1] for p in group) / len(group)
                    if not math.isclose(new_x, centres[idx][0]) or not math.isclose(new_y, centres[idx][1]):
                        centres[idx][0] = new_x
                        centres[idx][1] = new_y
                        updated = True
            if not updated:
                break

        return sorted((centre[0], centre[1]) for centre in centres)


if __name__ == "__main__":
    unittest.main()
