from abc import (
    ABC,
    abstractmethod,
)
import logging
import os
import shutil
import time
from typing import (
    List,
    Dict,
    Any,
    Iterable,
    Optional,
)
import urllib.parse

import requests

from src.matrix_info import MatrixInfo
from src.utils import (
    convert_size,
    file_id,
    remove_ext,
)
from botocore.exceptions import ClientError
from more_itertools import first

log = logging.getLogger(__name__)


class MatrixProvider(ABC):

    def __init__(self, **kwargs):
        """
        :param kwargs:
        Optional: blacklist: Iterable[str] - matrices to skip.
        """
        self.blacklist = frozenset(kwargs.get('blacklist', []))

    @abstractmethod
    def get_entity_ids(self) -> List[str]:
        """
        Obtain identifiers for matrix sources.
        What the ids refer to can vary depending on matrix source (e.g. object
        keys for canned S3, project ids for HCA service).
        """
        raise NotImplementedError

    @abstractmethod
    def obtain_matrix(self, entity_id: str) -> MatrixInfo:
        """
        Acquire matrix file in cwd.
        :param entity_id: identifier of the matrix source.
        :return: info of the downloaded matrix.
        """
        raise NotImplementedError

    def __iter__(self):
        """
        Download matrices and yield info objects.
        """
        entity_ids = self.get_entity_ids()
        log.info(f'Found {len(entity_ids)} target entities, {len(self.blacklist)} of which may be blacklisted.')
        for entity_id in entity_ids:
            if entity_id in self.blacklist:
                log.info(f'Skipping blacklisted matrix {entity_id}')
            else:
                yield self.obtain_matrix(entity_id)


class CannedMatrixProvider(MatrixProvider):
    mtx_ext = '.mtx.zip'

    def __init__(self, **kwargs):
        """
        :param kwargs:
        Required: s3_service: boto3.client - AWS S3 client
        Other params defined in superclass.
        """
        self.s3 = kwargs.pop('s3_service')
        super().__init__(**kwargs)

    def get_entity_ids(self) -> List[str]:
        """List matrix objects in S3 bucket."""
        keys = self.s3.list_bucket('matrices')
        return [file_id(key)
                for key in keys
                if key.endswith(self.mtx_ext)]

    def obtain_matrix(self, matrix_id) -> MatrixInfo:
        """Download matrix from S3."""
        log.info(f'Downloading matrix {matrix_id} from S3.')
        filename = matrix_id + self.mtx_ext
        self.s3.download('matrices', filename)
        assert filename in os.listdir('.')  # confirm successful download
        size = os.path.getsize(filename)  # in bytes
        log.info(f'Size of {filename}: {convert_size(size)}')
        return MatrixInfo(source='canned',
                          project_uuid=matrix_id,
                          zip_path=filename,
                          extract_path=remove_ext(filename, '.zip'))


class FreshMatrixProvider(MatrixProvider):
    project_id_field = 'project.provenance.document_id'
    min_gene_count_field = 'genes_detected'
    mtx_feature = 'gene'
    mtx_format = 'mtx'

    def __init__(self, **kwargs):
        """
        :param kwargs:
        Required:
            hca_endpoint: str - URL of HCA matrix service
            azul_endpoint: str - URL of azul service
        Optional:
            min_gene_count: int - Minimum genes for cells to be included in
            downloaded matrix.
        Other params defined in superclass.
        """
        self.hca_endpoint = kwargs.pop('hca_endpoint')
        self.azul_endpoint = kwargs.pop('azul_endpoint')
        self.min_gene_count = kwargs.pop('min_gene_count', 0)
        super().__init__(**kwargs)

        self.projects = self._get_project_uuids_from_azul()

    def get_entity_ids(self):
        """Return list matrix directory names (with prefix keys) from matrix service"""
        response = requests.get(f'{self.hca_endpoint}filters/{self.project_id_field}')
        self.check_response(response)
        return list(response.json()['cell_counts'].keys())

    def obtain_matrix(self, project_id: str) -> MatrixInfo:
        log.info(f'Requesting matrix from project {project_id} from HCA.')
        project_title = self.get_project_title(project_id)
        if project_title is None:
            log.info(f'No project title found for project ID {project_id} in Azul')
        else:
            log.info(f'Project title: {project_title}')

        status_response = self._request_matrix(project_id)
        assert status_response.status_code == 200
        s3_download_url = status_response.json()['matrix_url']
        log.info(f'Download URL for matrix is {s3_download_url}')

        matrix_response = requests.get(s3_download_url, stream=True)
        matrix_zipfile_name = os.path.basename(s3_download_url)

        with open(matrix_zipfile_name, 'wb') as matrix_zipfile:
            shutil.copyfileobj(matrix_response.raw, matrix_zipfile)

        return MatrixInfo(source='fresh',
                          project_uuid=project_id,
                          zip_path=matrix_zipfile_name,
                          extract_path=remove_ext(matrix_zipfile_name, '.zip'))

    def _request_matrix(self, project_document_id: str) -> requests.models.Response:

        list_projects_url = self.hca_endpoint + 'filters/' + self.project_id_field
        assert project_document_id in requests.get(list_projects_url).json()['cell_counts']

        payload = {
            'feature': self.mtx_feature,
            'format': self.mtx_format,
            'filter': {
                'op': 'and',
                'value': [
                    {
                        'op': '=',
                        'value': project_document_id,
                        'field': self.project_id_field
                    },
                    {
                        'op': '>=',
                        'value': self.min_gene_count,
                        'field': self.min_gene_count_field
                    }
                ]
            }
        }

        log.info(f'Requesting expression matrix for project document ID {project_document_id}')
        log.info(f'Request payload and filter settings: {payload}')
        response = requests.post(self.hca_endpoint + 'matrix', json=payload)
        self.check_response(response)
        minute_counter = 0
        while True:
            status_response = requests.get(f'{self.hca_endpoint}matrix/{response.json()["request_id"]}')
            status = status_response.json()['status']
            if status == 'Complete':
                break
            elif status == 'In Progress':
                log.info(f'Matrix request status: {status_response.json()["status"]}...')
                time.sleep(30)
                minute_counter += 0.5
            else:
                raise RuntimeError(f'Matrix service returned unexpected request status: {status}')
        log.info(f'Successfully requested matrix in {minute_counter} min.')

        return status_response

    def _get_project_uuids_from_azul(self) -> List[Dict[str, Any]]:
        """Get all project UUIDs from Azul by using the service APIs search_after query parameter."""
        search_after = ''
        while True:
            response = requests.get(self.azul_endpoint + search_after)
            try:
                hits = response.json()['hits']
            except KeyError:
                break

            for hit in hits:
                yield {
                    'project_title': first(hit['projects'])['projectTitle'],
                    'project_UUID': hit['entryId']
                }

            search_after = '?' + self._make_string_url_compliant_for_search_after(
                project_title=first(hits[-1]['projects'])['projectTitle'],
                document_id=hits[-1]['entryId']
            )

    @staticmethod
    def _make_string_url_compliant_for_search_after(project_title: str, document_id: str) -> str:
        """Return input string to be URL compliant, i.e., replacing special characters by their
         corresponding hexadecimal representation."""
        project_title = urllib.parse.quote(project_title)
        document_id = urllib.parse.quote(f'#{document_id}')
        return f'search_after={project_title}&search_after_uid=doc{document_id}'

    @staticmethod
    def check_response(response):
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            log.warning(f'{str(err)}')

    def get_project_title(self, project_id: str) -> Optional[str]:
        matches = (project['project_title'] for project in self.projects if project['project_UUID'] == project_id)
        return first(matches, None)
