import os
import unittest

from src import config
from src.matrix_info import MatrixInfo
from src.s3_service import S3Service
from src.utils import TemporaryDirectoryChange
from test.s3_test_case import S3TestCase


class TestS3Service(S3TestCase):

    def setUp(self) -> None:
        super().setUp()
        self.s3 = S3Service()

    def test_list_bucket(self):
        target = 'matrices'
        keys = self.s3.list_bucket(target)
        self.assertEqual(keys, [])

        target_key = config.s3_canned_matrix_prefix + 'foo'
        self.client.put_object(Bucket=config.s3_bucket_name,
                               Key=target_key,
                               Body=b'Hi')
        self.client.put_object(Bucket=config.s3_bucket_name,
                               Key='non-target',
                               Body=b'Bye')
        keys = self.s3.list_bucket(target)
        self.assertEqual(keys, [target_key])

    def test_download(self):
        key = 'hi'
        self.client.put_object(Bucket=config.s3_bucket_name,
                               Key=config.s3_canned_matrix_prefix + key,
                               Body=b'Hi')
        with TemporaryDirectoryChange():
            self.s3.download('matrices', key)
            self.assertEqual(os.listdir('.'), [key])

    def test_get_blacklist(self):
        self.client.put_object(Bucket=config.s3_bucket_name,
                               Key=f'blacklist',
                               Body=b'123\n456\n789\n')

        blacklist = self.s3.get_blacklist()
        self.assertEqual(blacklist, ['123', '456', '789'])

    def test_upload_figures(self):
        figures_files = ['foo', 'bar', 'baz']
        figures_dir = 'figures'
        project_uuid = '123'
        with TemporaryDirectoryChange():
            os.mkdir(figures_dir)
            for file in figures_files:
                with open(os.path.join(figures_dir, file), 'wb') as f:
                    f.write(b'')
            self.s3.upload_figures(MatrixInfo(source='nonexistent',
                                              zip_path=None,
                                              extract_path='N/A',
                                              project_uuid=project_uuid))
            found_objects = set(self.s3.list_bucket('figures'))
            expected_objects = {f'{config.s3_figures_prefix}{project_uuid}/{file}' for file in figures_files}
            self.assertEqual(found_objects, expected_objects)


if __name__ == '__main__':
    unittest.main()
