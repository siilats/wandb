import logging
import os
from typing import TYPE_CHECKING, NamedTuple, Optional

import wandb

if TYPE_CHECKING:
    import queue

    from wandb.filesync import dir_watcher, stats, step_upload
    from wandb.sdk.internal import file_stream, internal_api


class EventJobDone(NamedTuple):
    job: "UploadJob"
    success: bool


logger = logging.getLogger(__name__)


class UploadJob:
    def __init__(
        self,
        done_queue: "queue.Queue[step_upload.Event]",
        stats: "stats.Stats",
        api: "internal_api.Api",
        file_stream: "file_stream.FileStreamApi",
        silent: bool,
        save_name: "dir_watcher.SaveName",
        path: "dir_watcher.PathStr",
        artifact_id: Optional[str],
        md5: Optional[str],
        copied: bool,
        save_fn: Optional["step_upload.SaveFn"],
        digest: Optional[str],
    ) -> None:
        """A file upload thread.

        Arguments:
            done_queue: queue.Queue in which to put an EventJobDone event when
                the upload finishes.
            push_function: function(save_name, actual_path) which actually uploads
                the file.
            save_name: string logical location of the file relative to the run
                directory.
            path: actual string path of the file to upload on the filesystem.
        """
        self._done_queue = done_queue
        self._stats = stats
        self._api = api
        self._file_stream = file_stream
        self.silent = silent
        self.save_name = save_name
        self.save_path = self.path = path
        self.artifact_id = artifact_id
        self.md5 = md5
        self.copied = copied
        self.save_fn = save_fn
        self.digest = digest

    async def run(self) -> None:
        # wandb.termlog("SRP: in wandb/filesync/upload_job.py:UploadJob.run()")
        success = False
        try:
            success = await self.push()
        finally:
            # import remote_pdb; remote_pdb.set_trace(port=57855)
            # wandb.termlog(f"SRP: UploadJob: push completed, success={success}")
            if self.copied and os.path.isfile(self.save_path):
                os.remove(self.save_path)
            if success:
                self._file_stream.push_success(self.artifact_id, self.save_name)  # type: ignore
            # wandb.termlog(f"SRP: UploadJob: pushing EventJobDone")
            self._done_queue.put(EventJobDone(self, success))
            # wandb.termlog(f"SRP: UploadJob: pushed EventJobDone")

    async def push(self) -> bool:
      # wandb.termlog(f"SRP: pushing {self.save_name} to {self.path}; art={self.artifact_id}, md5={self.md5}")
      try:
        if self.save_fn:
            # Retry logic must happen in save_fn currently
            try:
                deduped = await self.save_fn(
                    lambda _, t: self._stats.update_uploaded_file(self.save_path, t)
                )
            except Exception as e:
                self._stats.update_failed_file(self.save_path)
                logger.exception("Failed to upload file: %s", self.save_path)
                wandb.util.sentry_exc(e)
                message = str(e)
                # TODO: this is usually XML, but could be JSON
                if hasattr(e, "response"):
                    message = e.response.content  # type: ignore[attr-defined]
                wandb.termerror(
                    'Error uploading "{}": {}, {}'.format(
                        self.save_path, type(e).__name__, message
                    )
                )
                return False

            if deduped:
                logger.info("Skipped uploading %s", self.save_path)
                self._stats.set_file_deduped(self.save_path)
            else:
                logger.info("Uploaded file %s", self.save_path)
            return True

        if self.md5:
            # This is the new artifact manifest upload flow, in which we create the
            # database entry for the manifest file before creating it. This is used for
            # artifact L0 files. Which now is only artifact_manifest.json
            _, response = self._api.create_artifact_manifest(
                self.save_name, self.md5, self.artifact_id
            )
            upload_url = response["uploadUrl"]
            upload_headers = response["uploadHeaders"]
        else:
            # The classic file upload flow. We get a signed url and upload the file
            # then the backend handles the cloud storage metadata callback to create the
            # file entry. This flow has aged like a fine wine.
            project = self._api.get_project()
            # wandb.termlog(f"SRP: asking to upload {self.save_name}")
            _, upload_headers, result = await self._api.upload_urls_async(project, [self.save_name])
            # wandb.termlog(f"SRP: finished asking to upload {self.save_name}")
            file_info = result[self.save_name]
            upload_url = file_info["url"]

        if upload_url is None:
            logger.info("Skipped uploading %s", self.save_path)
            self._stats.set_file_deduped(self.save_name)
        else:
            extra_headers = {}
            for upload_header in upload_headers:
                key, val = upload_header.split(":", 1)
                extra_headers[key] = val
            # Copied from push TODO(artifacts): clean up
            # If the upload URL is relative, fill it in with the base URL,
            # since its a proxied file store like the on-prem VM.
            if upload_url.startswith("/"):
                upload_url = f"{self._api.api_url}{upload_url}"
            try:
                with open(self.save_path, "rb") as f:
                    # wandb.termlog(f"SRP: saving {self.save_path} / {f} to {upload_url}")
                    try:
                        # self._api.upload_file(
                        await self._api.upload_file_async(
                            upload_url,
                            f,
                            lambda _, t: self.progress(t),
                            extra_headers=extra_headers,
                        )
                        # wandb.termlog(f"SRP: finished saving {self.save_path} / {f} to {upload_url}")
                    except Exception as e:
                        # wandb.termlog(f"SRP: failed to save {self.save_path} -- {e}")
                        raise
                logger.info("Uploaded file %s", self.save_path)
            except Exception as e:
                self._stats.update_failed_file(self.save_name)
                logger.exception("Failed to upload file: %s", self.save_path)
                wandb.util.sentry_exc(e)
                if not self.silent:
                    wandb.termerror(
                        'Error uploading "{}": {}, {}'.format(
                            self.save_name, type(e).__name__, e
                        )
                    )
                return False
        return True
      except Exception as e:
        wandb.termerror(f"SRP: exception in push: {e}")
        raise

    def progress(self, total_bytes: int) -> None:
        self._stats.update_uploaded_file(self.save_name, total_bytes)
