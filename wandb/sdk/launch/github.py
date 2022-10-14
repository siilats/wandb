from dataclasses import dataclass
from enum import IntEnum
from typing import Optional


PREFIX_HTTPS = "https://"
PREFIX_SSH = "git@"
SUFFIX_GIT = ".git"


class ReferenceType(IntEnum):
    BRANCH = 1
    COMMIT = 2


@dataclass
class GitHubReference:

    # TODO: Do we need to handle username, password, port?
    host: str

    organization: str
    repo: str

    # TODO: Enum? Literal type?
    view: Optional[str] = None  # tree or blob

    # Set when we don't know how to parse yet
    path: Optional[str] = None

    # Set when we do know
    default_branch: Optional[str] = None

    ref: Optional[str] = None  # branch or commit
    ref_type: Optional[ReferenceType] = None

    directory: Optional[str] = None
    entry_point: Optional[str] = None

    def repo_url(self) -> str:
        return f"{PREFIX_HTTPS}{self.host}/{self.organization}/{self.repo}"

    def repo_ssh(self) -> str:
        return f"{PREFIX_SSH}{self.host}:{self.organization}/{self.repo}{SUFFIX_GIT}"

    def url(self) -> str:
        url = self.repo_url()
        if self.view:
            url += f"/{self.view}"
        if self.path:
            url += f"/{self.path}"
        elif self.ref:
            url += f"/{self.ref}"
            if self.directory:
                url += f"/{self.directory}"
            if self.entry_point:
                url += f"/{self.entry_point}"
        return url


def parse_github_uri(uri: str) -> Optional[GitHubReference]:
    """
    Attempt to parse a string as a GitHub URL.
    """
    if uri.startswith(PREFIX_HTTPS):
        index = uri.find("/", len(PREFIX_HTTPS))
        if index > 0:
            host = uri[len(PREFIX_HTTPS) : index]
            path = uri[index + 1 :]
        else:
            # Could not parse host name
            return None
    elif uri.startswith(PREFIX_SSH):
        index = uri.find(":", len(PREFIX_SSH))
        if index > 0:
            host = uri[len(PREFIX_SSH) : index]
            path = uri[index + 1 :]
        else:
            # Could not parse host name
            return None
    else:
        return None

    parts = path.split("/")
    if len(parts) < 2:
        # Invalid - we need at least an organization and repo.
        return None
    organization = parts[0]
    repo = parts[1]
    if repo.endswith(SUFFIX_GIT):
        repo = repo[: -len(SUFFIX_GIT)]
    view = parts[2] if len(parts) > 2 else None
    path = "/".join(parts[3:])

    return GitHubReference(host, organization, repo, view, path)
