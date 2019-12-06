import os


class Config:

    @property
    def deployment_stage(self) -> str:
        return os.environ['DPSS_DEPLOYMENT_STAGE']

    @property
    def use_blacklist(self) -> bool:
        return os.environ['DPSS_BLACKLIST'] == '1'

    @property
    def matrix_source(self) -> str:
        return os.environ['DPSS_MATRIX_SOURCE']

    @property
    def stage_str(self) -> str:
        return '' if self.deployment_stage == 'prod' else f'{self.deployment_stage}.'

    @property
    def azul_project_endpoint(self) -> str:
        return f'https://service.{self.stage_str}explore.data.humancellatlas.org/repository/projects/'

    @property
    def hca_matrix_service_endpoint(self) -> str:
        return f'https://matrix.{self.stage_str}data.humancellatlas.org/v1/'

    @property
    def s3_bucket_name(self) -> str:
        return f'{self.stage_str}project-assets.data.humancellatlas.org'

    @property
    def s3_canned_matrix_prefix(self) -> str:
        return 'project-assets/project-matrices/'

    @property
    def s3_figures_prefix(self) -> str:
        return 'project-assets/project-stats/'


config = Config()
