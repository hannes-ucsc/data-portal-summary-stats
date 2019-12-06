import gzip
import logging
import os
import warnings

import numpy as np
import pandas as pd
import shutil
from typing import (
    List,
    Tuple,
    Callable,
    Union,
    FrozenSet,
)
from zipfile import ZipFile

from src.matrix_info import MatrixInfo
from src.utils import (
    DirectoryChange,
    remove_ext,
)

log = logging.getLogger(__name__)


class MatrixPreparer:
    lca_column = 'library_preparation_protocol.library_construction_method.ontology_label'

    hca_zipped_filenames = {
        'genes': 'genes.tsv.gz',
        'barcodes': 'cells.tsv.gz',
        'matrix': 'matrix.mtx.gz'
    }

    hca_filenames = {
        'genes': 'genes.tsv',
        'barcodes': 'cells.tsv',
        'matrix': 'matrix.mtx'
    }

    scanpy_filenames = {
        'genes': 'genes.tsv',
        'barcodes': 'barcodes.tsv',
        'matrix': 'matrix.mtx'
    }

    scanpy_tsv_columns = {
        # library_method_column is included because it is needed for separation,
        # not for scanpy
        'barcodes': ['cellkey', lca_column],
        'genes': ['featurekey', 'featurename']
    }

    def __init__(self, mtx_info: MatrixInfo):
        self.info = mtx_info

    def unzip(self) -> None:
        """
        Extract files from top-level zip archive, uncompress .gz files, and
        remove archive.
        """
        log.info(f'Unzipping {self.info.zip_path}')
        os.mkdir(self.info.extract_path)
        with ZipFile(self.info.zip_path) as zipfile:
            for member in zipfile.namelist():
                filename = os.path.basename(member)
                source = zipfile.open(member)
                target = open(os.path.join(self.info.extract_path, filename), 'wb')
                with source, target:
                    shutil.copyfileobj(source, target)
        os.remove(self.info.zip_path)

        extracted_files = os.listdir(self.info.extract_path)
        assert 3 <= len(extracted_files) <= 4  # optional readme
        assert all(filename in extracted_files for filename in self.hca_zipped_filenames.values())

        with DirectoryChange(self.info.extract_path):
            for gzfilename in self.hca_zipped_filenames.values():
                with gzip.open(gzfilename, 'rb') as gzfile:
                    filename = remove_ext(gzfilename, '.gz')
                    with open(filename, 'wb') as outfile:
                        shutil.copyfileobj(gzfile, outfile)
                        os.remove(gzfilename)

    def preprocess(self):
        """
        Extract gzip files and transform for ScanPy compatibility.
        """
        with DirectoryChange(self.info.extract_path):
            for filekey, filename in self.hca_filenames.items():
                log.info(f'Processing file {filename}')
                if filename.endswith('.tsv'):
                    self._preprocess_tsv(filename, self.scanpy_tsv_columns[filekey])
                elif filename.endswith('.mtx'):
                    self._preprocess_mtx(filename)
                os.rename(filename, self.scanpy_filenames[filekey])

    def prune(self, keep_frac: float) -> None:
        """
        Shrink matrix by removing entries at random to reach a desired fraction
        of the original size.
        :param keep_frac: the fraction of entries to keep, e.g. 0.05 to remove
        95% of the entries.
        :return: nothing, operations occurs on disk.
        """
        if not (0 < keep_frac <= 1):
            raise ValueError(f'Invalid prune fraction: {keep_frac}')
        mtx_path = os.path.join(self.info.extract_path, self.scanpy_filenames['matrix'])
        header, mtx = self._read_matrixmarket(mtx_path)
        entries = np.arange(1, mtx.index.size)
        keep_rows = np.random.choice(entries, round(keep_frac * entries.size), replace=False)
        mtx = self._filter_matrix_entries(mtx, pd.Series(keep_rows))
        self._write_matrixmarket(mtx_path, header, mtx)

    def separate(self) -> List[MatrixInfo]:
        """
        Split matrix into independent entities based on library construction approach.

        If the LCA is homogeneous, no change is made to the directory structure.
        Otherwise, a new directory is created within the extraction directory
        for every observed LCA and populated with the subset of matrix.mtx
        corresponding to that approach.
        Links are created for the row and column tsv files, which remain in the
        top-level extraction dir.
        :return: series of MatrixInfo objects describing the results of the
        separation.
        """
        log.info('Separating by library construction method...')

        with DirectoryChange(self.info.extract_path):
            barcodes_file = self.scanpy_filenames['barcodes']
            barcodes = self._read_tsv(barcodes_file, False)
            lib_con_data = barcodes.pop(barcodes.columns[1])
            self._write_tsv(barcodes_file, barcodes)

            found_lcas = frozenset(lib_con_data.unique())
            assert len(found_lcas) > 0

            if not self.info.lib_con_approaches:
                self.info.lib_con_approaches = found_lcas
            elif self.info.lib_con_approaches != found_lcas:
                raise RuntimeError(
                    'The provided matrix library construction approach does not match the extracted files:'
                    f'Provided: {self.info} Found: {found_lcas}'
                )

            if len(self.info.lib_con_approaches) == 1:
                log.info('Homogeneous LCA.')
                return [self.info]
            else:
                for lca in self.info.lib_con_approaches:
                    log.info(f'Consolidating {lca} cells')
                    os.mkdir(lca)

                    def matrix_filter(entry):
                        barcode_lineno = entry[1]
                        entry_lca = lib_con_data.iloc[barcode_lineno - 1]
                        return entry_lca == lca

                    with DirectoryChange(lca):
                        for filekey, filename in self.scanpy_filenames.items():
                            if filekey == 'matrix':
                                header, mtx = self._read_matrixmarket(f'../{filename}')
                                mtx = self._filter_matrix_entries(mtx, matrix_filter)
                                self._write_matrixmarket(filename, header, mtx)
                            else:
                                os.symlink(f'../{filename}', filename)

                return [MatrixInfo(source=self.info.source,
                                   project_uuid=self.info.project_uuid,
                                   zip_path=None,
                                   extract_path=os.path.join(self.info.extract_path, lca),
                                   lib_con_approaches=frozenset({lca}))
                        for lca in self.info.lib_con_approaches]

    def rezip(self, zip_path: str = None, remove_dir: bool = False) -> None:
        """
        Compress unprocessed files to zip archive.
        This is the inverse operation of `unzip`.
        :param remove_dir: whether the extraction directory should be removed
        after zipping.
        :param zip_path: path of resulting zip archive. Updates matrix info if
        provided.
        """
        if zip_path is not None:
            self.info.zip_path = zip_path

        with ZipFile(self.info.zip_path, 'w') as zipfile:
            with DirectoryChange(self.info.extract_path):
                for gzfilename, filename in zip(self.hca_zipped_filenames.values(),
                                                self.hca_filenames.values()):
                    with open(filename, 'rb') as infile:
                        with gzip.open(gzfilename, 'wb') as gzfile:
                            shutil.copyfileobj(infile, gzfile)
                            os.remove(filename)
                    zipfile.write(gzfilename)

        if remove_dir:
            shutil.rmtree(self.info.extract_path)

    @classmethod
    def _filter_matrix_entries(cls,
                               mtx: pd.DataFrame,
                               which_rows: Union[pd.Series, Callable[[pd.Series], bool]]) -> pd.DataFrame:
        """
        Remove rows from a matrix-market format matrix file, leaving the row and
        column files unchanged.
        :param mtx: dataframe of matrix entries in matrix market format.
        :param which_rows: predicate function or Series of integer indices.
        :return: the modified matrix.
        """
        if callable(which_rows):
            keep_labels = mtx.iloc[1:].apply(which_rows, axis=1)
            mtx = mtx.drop(labels=1 + np.flatnonzero(~keep_labels))
        else:
            mtx = mtx.iloc[pd.concat([pd.Series(0), which_rows])]
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            # Pandas complains about this modification because it at this point
            # `mtx` is a slice of of the original parameter and the following
            # assignment will not propagate past the slice. Which is exactly
            # what is intended here.
            mtx.iloc[0, 2] = mtx.index.size - 1
        return mtx

    @classmethod
    def _preprocess_tsv(cls,
                        filename: str,
                        keep_cols: List[str]) -> None:
        """
        :param filename: name of un-gzipped, unprocessed file
        :param keep_cols: columns to keep.
        """
        df = cls._read_tsv(filename, True)
        assert all(col in df.columns for col in keep_cols)
        df = df[keep_cols]
        cls._write_tsv(filename, df)

    @classmethod
    def _preprocess_mtx(cls,
                        filename: str) -> None:
        # ScanPy requires gene expression to be int for some reason
        # TODO Normalize?
        header, df = cls._read_matrixmarket(filename)
        df.iloc[:, 2] = np.rint(df.iloc[:, 2]).astype(int)
        cls._write_matrixmarket(filename, header, df)

    @classmethod
    def _read_tsv(cls, path: str, header: bool, **pd_kwargs) -> pd.DataFrame:
        if not header:
            pd_kwargs['header'] = None
        return pd.read_csv(path, index_col=None, sep='\t', **pd_kwargs)

    @classmethod
    def _write_tsv(cls, path: str, df: pd.DataFrame, **pd_kwargs) -> None:
        df.to_csv(path, index=False, header=False, sep='\t', **pd_kwargs)

    @classmethod
    def _read_matrixmarket(cls, path: str, **pd_kwargs) -> Tuple[str, pd.DataFrame]:
        with open(path) as f:
            header = f.readline()
        assert header.startswith('%')
        # float_precision is needed here or gene expression accumulates rounding
        # errors that cause rows to compare unequal
        df = pd.read_csv(path, header=None, comment='%', sep=' ', float_precision='round_trip', **pd_kwargs)
        return header, df

    @classmethod
    def _write_matrixmarket(cls, path: str, header: str, df: pd.DataFrame, **pd_kwargs) -> None:
        # ScanPy needs MatrixMarket header even though pandas can't read it
        with open(path, 'w') as f:
            f.write(header)
        df.to_csv(path, index=False, header=False, sep=' ', mode='a', **pd_kwargs)
