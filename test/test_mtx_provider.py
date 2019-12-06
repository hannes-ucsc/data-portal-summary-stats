from abc import (
    abstractmethod,
    ABC,
)
import os
import unittest

import responses

from src import config
from src.matrix_provider import (
    CannedMatrixProvider,
    FreshMatrixProvider,
)
from src.s3_service import S3Service
from src.utils import TemporaryDirectoryChange
from test.s3_test_case import S3TestCase
from test.tempdir_test_case import TempdirTestCase


class TestMatrixProvider(ABC):

    @abstractmethod
    def test_get_entity_ids(self):
        raise NotImplementedError

    @abstractmethod
    def test_obtain_matrix(self):
        raise NotImplementedError


class TestFresh(TempdirTestCase, TestMatrixProvider):
    project_field_name = 'project.provenance.document_id'
    azul_endpoint = 'https://service.explore.data.humancellatlas.org/repository/projects/'
    hca_endpoint = 'https://matrix.data.humancellatlas.org/v1/'

    def setUp(self):
        super().setUp()
        self.provider = FreshMatrixProvider(blacklist=['bad'])

    @responses.activate
    def test_get_entity_ids(self):
        cell_counts = {
            '08e7b6ba-5825-47e9-be2d-7978533c5f8c': 2,
            '425efc0a-d3fe-4fab-9f74-3bd829ebdf01': 1,
            '84e01f35-4f77-4e07-ac7b-058f545d782a': 1
        }

        responses.add(
            responses.GET,
            f'{self.hca_endpoint}filters/{self.project_field_name}',
            json={
                'cell_counts': cell_counts,
                'field_description': 'Unique identifier for overall project.',
                'field_name': self.project_field_name,
                'field_type': 'categorical'
            }
        )
        observed_list = self.provider.get_entity_ids()
        self.assertEqual(set(observed_list), set(cell_counts.keys()))

    @responses.activate
    def test_obtain_matrix(self):
        request_id = '3c44455c-d751-4fc9-a119-3a55c05f8990'
        url_get1 = os.path.join(self.hca_endpoint, 'filters/project.provenance.document_id')
        url_post = os.path.join(self.hca_endpoint, 'matrix')
        url_get2 = os.path.join(self.hca_endpoint + f'matrix/{request_id}')
        matrix_url = 'https://s3.amazonaws.com/fake-matrix-service-results/0/424242/13-13.mtx.zip'

        # First response: GET (to satisfy the assertion):
        responses.add(
            responses.GET,
            url_get1,
            json={
                'cell_counts': {
                    'e7d811e2-832a-4452-85a5-989e2f8267bf': 2,
                },
            })

        # Second response: POST:
        responses.add(
            responses.POST,
            url_post,
            json={
                'message': 'Job started.',
                'non_human_request_ids': {},
                'request_id': request_id,
                'status': 'In Progress'
            },
            status=202)

        # Third response: GET returns in progress:
        responses.add(
            responses.GET,
            url_get2,
            json={'status': 'In Progress'})

        # Fourth response: GET returns "complete":
        responses.add(
            responses.GET,
            url_get2,
            json={
                'eta': '',
                'matrix_url': matrix_url,
                'message': f'Request {request_id} has successfully ...',
                'request_id': request_id,
                'status': 'Complete'
            },
            status=200)

        # Fifth response: GET in get_expression_matrix_from_service
        responses.add(responses.GET, matrix_url, status=200, stream=True)

        responses.add(responses.GET,
                      self.azul_endpoint,
                      json={
                          'foo': 'bar'
                      })

        mtx_info = self.provider.obtain_matrix('e7d811e2-832a-4452-85a5-989e2f8267bf')
        self.assertEqual(mtx_info.zip_path, '13-13.mtx.zip')


class TestCanned(TempdirTestCase, S3TestCase, TestMatrixProvider):

    def setUp(self) -> None:
        TempdirTestCase.setUp(self)
        S3TestCase.setUp(self)
        self.provider = CannedMatrixProvider(blacklist=['bad'],
                                             s3_service=S3Service())

    def tearDown(self):
        S3TestCase.tearDown(self)
        TempdirTestCase.tearDown(self)

    def test_get_entity_ids(self):
        uuids = {'123', '456', '789', 'bad'}
        for uuid in uuids:
            self.client.put_object(Bucket=self.bucket_name,
                                   Key=f'{config.s3_canned_matrix_prefix}{uuid}.mtx.zip')
        self.assertEqual(set(self.provider.get_entity_ids()), uuids)

    def test_obtain_matrix(self):
        uuid = '123'
        key = uuid + '.mtx.zip'
        with TemporaryDirectoryChange():
            self.client.put_object(Bucket=config.s3_bucket_name,
                                   Key=config.s3_canned_matrix_prefix + key)
            mtx_info = self.provider.obtain_matrix(uuid)
            self.assertEqual(os.listdir('.'), [key])
            self.assertEqual(mtx_info.zip_path, key)
            self.assertEqual(mtx_info.source, 'canned')


if __name__ == '__main__':
    unittest.main()
