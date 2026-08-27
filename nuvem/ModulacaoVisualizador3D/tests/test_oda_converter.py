# -*- coding: utf-8 -*-
"""Testes de oda_converter.py - nao dependem de uma instalacao real do
ODA File Converter: o subprocess.run e' mockado para simular sucesso e
falha na conversao."""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oda_converter import convert_dwg_to_dxf, OdaNotFoundError, OdaConversionError


def _fake_run_success(args, **kwargs):
    in_dir, out_dir = args[1], args[2]
    base_names = [os.path.splitext(f)[0] for f in os.listdir(in_dir)]
    for base_name in base_names:
        with open(os.path.join(out_dir, base_name + ".dxf"), "w") as f:
            f.write("0\nEOF\n")
    return mock.Mock(returncode=0, stdout="", stderr="")


def _fake_run_no_output(args, **kwargs):
    return mock.Mock(returncode=0, stdout="", stderr="")


class TestOdaConverter(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dwg_path = os.path.join(self.tmpdir, "planta.dwg")
        with open(self.dwg_path, "wb") as f:
            f.write(b"fake dwg content")
        self.fake_oda_exe = os.path.join(self.tmpdir, "ODAFileConverter.exe")
        with open(self.fake_oda_exe, "wb") as f:
            f.write(b"fake exe")

    def test_raises_when_oda_not_found(self):
        missing_exe = os.path.join(self.tmpdir, "nao_instalado", "ODAFileConverter.exe")
        with self.assertRaises(OdaNotFoundError):
            convert_dwg_to_dxf(self.dwg_path, oda_exe=missing_exe)

    @mock.patch("oda_converter.find_oda_converter", return_value=None)
    def test_raises_when_oda_not_found_via_autodetect(self, _mock_find):
        with self.assertRaises(OdaNotFoundError):
            convert_dwg_to_dxf(self.dwg_path)

    def test_raises_when_dwg_missing(self):
        missing = os.path.join(self.tmpdir, "nao_existe.dwg")
        with self.assertRaises(OdaConversionError):
            convert_dwg_to_dxf(missing, oda_exe=self.fake_oda_exe)

    @mock.patch("oda_converter.subprocess.run", side_effect=_fake_run_success)
    def test_converts_successfully_with_default_output_path(self, _mock_run):
        result = convert_dwg_to_dxf(self.dwg_path, oda_exe=self.fake_oda_exe)
        expected = os.path.join(self.tmpdir, "planta.dxf")
        self.assertEqual(result, expected)
        self.assertTrue(os.path.isfile(expected))

    @mock.patch("oda_converter.subprocess.run", side_effect=_fake_run_success)
    def test_converts_to_custom_output_path(self, _mock_run):
        custom_output = os.path.join(self.tmpdir, "saida", "resultado.dxf")
        result = convert_dwg_to_dxf(self.dwg_path, output_path=custom_output, oda_exe=self.fake_oda_exe)
        self.assertEqual(result, custom_output)
        self.assertTrue(os.path.isfile(custom_output))

    @mock.patch("oda_converter.subprocess.run", side_effect=_fake_run_no_output)
    def test_raises_when_conversion_produces_no_file(self, _mock_run):
        with self.assertRaises(OdaConversionError):
            convert_dwg_to_dxf(self.dwg_path, oda_exe=self.fake_oda_exe)


if __name__ == "__main__":
    unittest.main()
