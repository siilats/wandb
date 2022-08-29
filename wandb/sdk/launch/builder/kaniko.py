import base64
import json
import os
import tarfile
import tempfile
import time
from typing import Any, Dict, Optional

import kubernetes  # type: ignore
from kubernetes import client

import wandb
from wandb.errors import LaunchError
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.util import get_module

from .._project_spec import (
    EntryPoint,
    LaunchProject,
    create_metadata_file,
    get_entry_point_command,
)
from ..utils import LOG_PREFIX, get_kube_context_and_api_client, sanitize_wandb_api_key
from .build import _create_docker_build_ctx, generate_dockerfile

_DEFAULT_BUILD_TIMEOUT_SECS = 1800  # 30 minute build timeout


def _create_dockerfile_configmap(
    config_map_name: str, context_path: str
) -> client.V1ConfigMap:
    with open(os.path.join(context_path, "Dockerfile.wandb-autogenerated"), "rb") as f:
        docker_file_bytes = f.read()

    build_config_map = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(
            name=config_map_name, namespace="wandb", labels={"wandb": "launch"}
        ),
        binary_data={
            "Dockerfile": base64.b64encode(docker_file_bytes).decode("UTF-8"),
        },
        immutable=True,
    )
    return build_config_map


def _wait_for_completion(
    batch_client: client.BatchV1Api, job_name: str, deadline_secs: Optional[int] = None
) -> bool:
    start_time = time.time()
    while True:
        job = batch_client.read_namespaced_job_status(job_name, "wandb")
        if job.status.succeeded is not None and job.status.succeeded >= 1:
            return True
        elif job.status.failed is not None and job.status.failed >= 1:
            return False
        wandb.termlog(f"{LOG_PREFIX}Waiting for build job to complete...")
        if deadline_secs is not None and time.time() - start_time > deadline_secs:
            return False

        time.sleep(5)


class KanikoBuilder(AbstractBuilder):
    type = "kaniko"

    def __init__(self, builder_config: Dict[str, Any]):
        super().__init__(builder_config)
        self.config_map_name = builder_config.get(
            "config-map-name", "wandb-launch-build-context"
        )
        self.build_job_name = builder_config.get(
            "build-job-name", "wandb-launch-container-build"
        )
        cloud_provider = builder_config.get("cloud-provider", None)
        if cloud_provider is None or not isinstance(cloud_provider, str):
            raise LaunchError("Kaniko builder requires string cloud-provider")
        self.cloud_provider: str = cloud_provider.lower()
        self.instance_mode = False
        if not builder_config.get("credentials"):
            self.instance_mode = True
            # if no cloud provider info given, assume running in instance mode
            # kaniko pod will have access to build context store and ecr
            wandb.termlog(f"{LOG_PREFIX}Kaniko builder running in instance mode")

        self.build_context_store = builder_config.get("build-context-store", None)
        if self.build_context_store is None:
            raise LaunchError("build-context-store is not set in cloud-provider")
        credentials_config = builder_config.get("credentials", {})
        self.credentials_secret_name = credentials_config.get("secret-name")
        self.credentials_secret_mount_path = credentials_config.get("secret-mount-path")
        if bool(self.credentials_secret_name) != bool(
            self.credentials_secret_mount_path
        ):
            raise LaunchError(
                "Must provide secret-name and secret-mount-path or neither"
            )

    def _create_docker_ecr_config_map(
        self, corev1_client: client.CoreV1Api, repository: str
    ) -> None:
        if self.cloud_provider.lower() == "aws":
            if not self.instance_mode:
                ecr_config_map = client.V1ConfigMap(
                    api_version="v1",
                    kind="ConfigMap",
                    metadata=client.V1ObjectMeta(
                        name="docker-config",
                        namespace="wandb",
                    ),
                    data={"config.json": json.dumps({"credsStore": "ecr-login"})},
                    immutable=True,
                )
            else:
                wandb.termlog(
                    f"{LOG_PREFIX}Builder not supplied with credentials, assuming instance mode."
                )
                d = {
                    "config.json": json.dumps(
                        {"credHelpers": {repository.split(":")[0]: "ecr-login"}}
                    )
                }
                ecr_config_map = client.V1ConfigMap(
                    api_version="v1",
                    kind="ConfigMap",
                    metadata=client.V1ObjectMeta(
                        name="docker-config",
                        namespace="wandb",
                    ),
                    data=d,
                    immutable=True,
                )
            corev1_client.create_namespaced_config_map("wandb", ecr_config_map)

    def _delete_docker_ecr_config_map(self, client: client.CoreV1Api) -> None:
        client.delete_namespaced_config_map("docker-config", "wandb")

    def _upload_build_context(self, run_id: str, context_path: str) -> str:
        # creat a tar archive of the build context and upload it to s3
        context_file = tempfile.NamedTemporaryFile(delete=False)
        with tarfile.TarFile.open(fileobj=context_file, mode="w:gz") as context_tgz:
            context_tgz.add(context_path, arcname=".")
        context_file.close()
        if self.cloud_provider.lower() == "aws":
            boto3 = get_module(
                "boto3",
                "AWS cloud provider requires boto3, install with pip install wandb[launch]",
            )
            botocore = get_module(
                "botocore",
                "aws cloud-provider requires botocore,  install with pip install wandb[launch]",
            )

            s3_client = boto3.client("s3")

            try:
                s3_client.upload_file(
                    context_file.name, self.build_context_store, f"{run_id}.tgz"
                )
                os.remove(context_file.name)
            except botocore.exceptions.ClientError as e:
                os.remove(context_file.name)
                raise LaunchError(f"Failed to upload build context to S3: {e}")
            return f"s3://{self.build_context_store}/{run_id}.tgz"
        # TODO: support gcp and azure cloud providers
        elif self.cloud_provider.lower() == "gcp":
            storage = get_module(
                "google.cloud.storage",
                "gcp provider requires google-cloud-storage,  install with pip install wandb[launch]",
            )

            storage_client = storage.Client()
            try:
                bucket = storage_client.bucket(self.build_context_store)
                blob = bucket.blob(f"{run_id}.tgz")
                blob.upload_from_filename(context_file.name)
                os.remove(context_file.name)
            except Exception as e:
                os.remove(context_file.name)
                raise LaunchError(f"Failed to upload build context to GCP: {e}")
            return f"gs://{self.build_context_store}/{run_id}.tgz"
        else:
            raise LaunchError("Unsupported storage provider")

    def check_build_required(
        self, repository: str, launch_project: LaunchProject
    ) -> bool:
        # TODO(kyle): Robustify to remote the trycatch
        try:
            ecr_provider = self.cloud_provider.lower()
            if ecr_provider == "aws" and repository:
                # TODO: pass in registry config
                region = repository.split(".")[3]
                boto3 = get_module(
                    "boto3",
                    "AWS ECR requires boto3,  install with pip install wandb[launch]",
                )
                ecr_client = boto3.client("ecr", region_name=region)
                repo_name = repository.split("/")[-1]
                try:
                    ecr_client.describe_images(
                        repositoryName=repo_name,
                        imageIds=[{"imageTag": launch_project.image_tag}],
                    )
                    return False
                except ecr_client.exceptions.ImageNotFoundException:
                    return True
            else:
                return True
        except Exception as e:
            wandb.termlog(
                f"{LOG_PREFIX}Failed while checking if build is required, defaulting to building: {e}"
            )
            return False

    def build_image(
        self,
        launch_project: LaunchProject,
        repository: Optional[str],
        entrypoint: EntryPoint,
        docker_args: Dict[str, Any],
    ) -> str:

        if repository is None:
            image_uri = launch_project.image_uri
        image_uri = f"{repository}:{launch_project.image_tag}"
        wandb.termlog(f"{LOG_PREFIX}Checking for image {image_uri}")
        if not self.check_build_required(repository, launch_project):
            return image_uri
        entry_cmd = " ".join(
            get_entry_point_command(entrypoint, launch_project.override_args)
        )

        # kaniko builder doesn't seem to work with a custom user id, need more investigation
        dockerfile_str = generate_dockerfile(
            launch_project, entrypoint, launch_project.resource, self.type
        )
        create_metadata_file(
            launch_project,
            image_uri,
            sanitize_wandb_api_key(entry_cmd),
            docker_args,
            sanitize_wandb_api_key(dockerfile_str),
        )
        context_path = _create_docker_build_ctx(launch_project, dockerfile_str)
        run_id = launch_project.run_id

        _, api_client = get_kube_context_and_api_client(
            kubernetes, launch_project.resource_args
        )
        build_job_name = f"{self.build_job_name}-{run_id}"
        config_map_name = f"{self.config_map_name}-{run_id}"

        build_context = self._upload_build_context(run_id, context_path)
        dockerfile_config_map = _create_dockerfile_configmap(
            config_map_name, context_path
        )
        build_job = self._create_kaniko_job(
            build_job_name,
            dockerfile_config_map.metadata.name,
            repository,
            image_uri,
            build_context,
        )
        wandb.termlog(f"{LOG_PREFIX}Created kaniko job {build_job_name}")

        # TODO: use same client as kuberentes.py
        batch_v1 = client.BatchV1Api(api_client)
        core_v1 = client.CoreV1Api(api_client)

        try:
            core_v1.create_namespaced_config_map("wandb", dockerfile_config_map)
            self._create_docker_ecr_config_map(core_v1, repository)
            batch_v1.create_namespaced_job("wandb", build_job)

            # wait for double the job deadline since it might take time to schedule
            if not _wait_for_completion(
                batch_v1, build_job_name, 3 * _DEFAULT_BUILD_TIMEOUT_SECS
            ):
                raise Exception(f"Failed to build image in kaniko for job {run_id}")
        except Exception as e:
            wandb.termerror(
                f"{LOG_PREFIX}Exception when creating Kubernetes resources: {e}\n"
            )
        finally:
            wandb.termlog(f"{LOG_PREFIX}Cleaning up resources")
            try:
                # should we clean up the s3 build contexts? can set bucket level policy to auto deletion
                core_v1.delete_namespaced_config_map(config_map_name, "wandb")
                self._delete_docker_ecr_config_map(core_v1)
                batch_v1.delete_namespaced_job(build_job_name, "wandb")
            except Exception as e:
                raise LaunchError(f"Exception during Kubernetes resource clean up {e}")

        return image_uri

    def _create_kaniko_job(
        self,
        job_name: str,
        config_map_name: str,
        repository: str,
        image_tag: str,
        build_context_path: str,
    ) -> "client.V1Job":
        env = None
        if self.instance_mode and self.cloud_provider.lower() == "aws":
            region = repository.split(".")[3]
            env = client.V1EnvVar(name="AWS_REGION", value=region)

        volume_mounts = [
            client.V1VolumeMount(
                name="build-context-config-map", mount_path="/etc/config"
            ),
            client.V1VolumeMount(name="docker-config", mount_path="/kaniko/.docker/"),
        ]
        volumes = [
            client.V1Volume(
                name="build-context-config-map",
                config_map=client.V1ConfigMapVolumeSource(
                    name=config_map_name,
                ),
            ),
            client.V1Volume(
                name="docker-config",
                config_map=client.V1ConfigMapVolumeSource(
                    name="docker-config",
                ),
            ),
        ]
        if (
            self.credentials_secret_name is not None
            and self.credentials_secret_mount_path is not None
        ):
            volume_mounts += [
                client.V1VolumeMount(
                    name=self.credentials_secret_name,
                    mount_path=self.credentials_secret_mount_path,
                    read_only=True,
                )
            ]
            volumes += [
                client.V1Volume(
                    name=self.credentials_secret_name,
                    secret=client.V1SecretVolumeSource(
                        secret_name=self.credentials_secret_name
                    ),
                )
            ]
        # Configurate Pod template container
        args = [
            f"--context={build_context_path}",
            "--dockerfile=/etc/config/Dockerfile",
            f"--destination={image_tag}",
            "--cache=true",
            f"--cache-repo={repository}",
            "--snapshotMode=redo",
        ]
        if env is not None:
            container = client.V1Container(
                name="wandb-container-build",
                image="gcr.io/kaniko-project/executor:latest",
                args=args,
                volume_mounts=volume_mounts,
                env=[env],
            )
        else:
            container = client.V1Container(
                name="wandb-container-build",
                image="gcr.io/kaniko-project/executor:latest",
                args=args,
                volume_mounts=volume_mounts,
            )
        # Create and configure a spec section
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"wandb": "launch"}),
            spec=client.V1PodSpec(
                restart_policy="Never",
                active_deadline_seconds=_DEFAULT_BUILD_TIMEOUT_SECS,
                containers=[container],
                volumes=volumes,
            ),
        )
        # Create the specification of job
        spec = client.V1JobSpec(template=template, backoff_limit=1)
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=job_name, namespace="wandb", labels={"wandb": "launch"}
            ),
            spec=spec,
        )

        return job
