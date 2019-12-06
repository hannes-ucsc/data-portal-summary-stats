#!./.venv/bin/python
import os
import shutil

from src.matrix_preparer import MatrixPreparer
from src.matrix_provider import CannedMatrixProvider
from src.s3_service import S3Service
from src.utils import DirectoryChange
from test.tempdir_test_case import MockMatrixTestCase


def main():
    os.environ['AWS_DEFAULT_PROFILE'] = 'hca-id'
    s3 = S3Service()
    provider = CannedMatrixProvider(s3_service=s3)
    with DirectoryChange('../test/'):
        print('Entering test directory')
        mtxinfo = next(iter(provider))
        print(f'Obtained matrix: {mtxinfo.zip_path}')
        prep = MatrixPreparer(mtxinfo)
        print('Processing...')
        prep.unzip()
        prep.prune(0.05)

    print('Copying to notebook dir')
    shutil.rmtree(f'../notebook/{mtxinfo.extract_path}', ignore_errors=True)
    shutil.copytree(f'../test/{mtxinfo.extract_path}', f'../notebook/{mtxinfo.extract_path}')

    with DirectoryChange('../notebook'):
        print('Preprocessing files for notebook')
        prep.preprocess()

    with DirectoryChange('../test/'):
        print('Recompressing')
        prep.rezip(remove_dir=True, zip_path=MockMatrixTestCase.mock_matrix)

    print('Finished.')


if __name__ == '__main__':
    main()
