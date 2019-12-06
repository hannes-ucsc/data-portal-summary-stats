#!/usr/env/python3

import logging
import time
import os

from src import config
from src.matrix_preparer import MatrixPreparer
from src.matrix_provider import (
    FreshMatrixProvider,
    CannedMatrixProvider,
)
from src.matrix_summary_stats import MatrixSummaryStats
from src.s3_service import S3Service
from src.utils import TemporaryDirectoryChange

log = logging.getLogger(__name__)

# Set up logging
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
# These libraries make a lot of debug-level log messages which make the log file hard to read
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


def main():
    log.info(f'\nGenerating per-project summary statistics of matrix data from '
             f'{config.deployment_stage} deployment environment.\n')

    s3 = S3Service()

    # Temporary work-around for matrices that can't be processed for various reasons.
    do_not_process = s3.get_blacklist() if config.use_blacklist else []

    if config.matrix_source == 'fresh':
        provider = FreshMatrixProvider(blacklist=do_not_process)
    elif config.matrix_source == 'canned':
        provider = CannedMatrixProvider(blacklist=do_not_process,
                                        s3_service=s3)
    else:
        assert False

    log.info(f'Processing {config.matrix_source} matrices...')
    iter_matrices = iter(provider)
    while True:
        with TemporaryDirectoryChange() as tempdir:
            try:
                mtx_info = next(iter_matrices)
            except StopIteration:
                break
            log.info(f'Writing to temporary directory {tempdir}')
            log.info(f'Processing matrix for project {mtx_info.project_uuid} ({mtx_info.source})')

            preparer = MatrixPreparer(mtx_info)
            preparer.unzip()
            preparer.preprocess()

            for sep_mtx_info in preparer.separate():
                log.info(f'Generating stats for {sep_mtx_info.extract_path}')
                mss = MatrixSummaryStats(sep_mtx_info)
                mss.create_images()
                s3.upload_figures(mtx_info)
                log.info('Finished uploading figures')

                # This logic was in Krause's code, no idea why
                if mtx_info.source == 'fresh':
                    time.sleep(15)
    log.info('Finished.')


if __name__ == "__main__":
    main()
