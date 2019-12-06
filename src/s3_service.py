import logging
import os
from typing import (
    List,
)

import boto3

from src import config
from src.matrix_info import MatrixInfo

log = logging.getLogger(__name__)


class S3Service:

    def __init__(self):
        log.info('Initializing S3 service...')
        self.client = boto3.client('s3')
        self.bucket_name = config.s3_bucket_name
        self.key_prefixes = {
            'matrices': config.s3_canned_matrix_prefix,
            'figures': config.s3_figures_prefix
        }

    def list_bucket(self, target: str) -> List[str]:
        response = self.client.list_objects_v2(Bucket=self.bucket_name,
                                               Prefix=self.key_prefixes[target])
        return [obj['Key'] for obj in response.get('Contents', [])]

    def download(self, target: str, filename: str) -> None:
        self.client.download_file(Bucket=self.bucket_name,
                                  Key=self.key_prefixes[target] + filename,
                                  Filename=filename)

    def get_blacklist(self) -> List[str]:
        response = self.client.get_object(Bucket=self.bucket_name, Key='blacklist')
        bytes_string = response['Body'].read()
        return bytes_string.decode().strip('\n').split('\n')

    def upload_figures(self, mtx_info: MatrixInfo) -> None:
        figures = os.listdir('figures/')
        for figure in figures:
            key = f'{self.key_prefixes["figures"]}{mtx_info.figures_folder}{figure}'
            log.info(f'Uploading {figure} to S3 bucket {self.bucket_name} as {key}')
            self.client.upload_file(Filename=f'figures/{figure}',
                                    Bucket=self.bucket_name,
                                    Key=key)
