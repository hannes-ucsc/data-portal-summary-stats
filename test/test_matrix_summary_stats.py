#!/usr/bin/env python3

import unittest
import os
import filecmp
from unittest import mock

from more_itertools import first

from src.matrix_preparer import MatrixPreparer
from src.matrix_summary_stats import MatrixSummaryStats
from test.tempdir_test_case import MockMatrixTestCase


class TestMatrixSummaryStats(MockMatrixTestCase):

    def setUp(self) -> None:
        super().setUp()
        preparer = MatrixPreparer(self.info)
        preparer.unzip()
        preparer.preprocess()
        new_info = first(preparer.separate())
        self.mss = MatrixSummaryStats(new_info)

    @mock.patch('src.matrix_summary_stats.MatrixSummaryStats.get_min_gene_count')
    def test_create_images(self, min_gene_method):
        # Prevent zero division error with small matrix in ScanPy methods
        min_gene_method.return_value = 0
        self.mss.create_images()
        fig_path = 'figures'
        figures_dir = os.listdir(fig_path)
        self.assertTrue('filter_genes_dispersion.png' in figures_dir)
        self.assertTrue('highest_expr_genes.png' in figures_dir)

        expected = 'figures'
        self.assertTrue(filecmp.cmpfiles(expected, fig_path, common='filter_genes_dispersion.png'))
        self.assertTrue(filecmp.cmpfiles(expected, fig_path, common='highest_expr_genes.png'))

        # TODO test more figures


if __name__ == "__main__":
    unittest.main()
