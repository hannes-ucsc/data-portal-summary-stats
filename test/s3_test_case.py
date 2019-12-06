import unittest

import boto3
from moto import (
    mock_sts,
    mock_s3,
)

from src import (
    config,
)


@mock_s3
@mock_sts
class S3TestCase(unittest.TestCase):

    def setUp(self) -> None:
        self.client = boto3.client('s3')
        self.client.create_bucket(Bucket=config.s3_bucket_name)

    def tearDown(self) -> None:
        response = self.client.list_objects_v2(Bucket=config.s3_bucket_name)
        keys = [obj['Key'] for obj in response.get('Contents', [])]
        for key in keys:
            self.client.delete_object(Bucket=config.s3_bucket_name,
                                      Key=key)
        self.client.delete_bucket(Bucket=config.s3_bucket_name)
