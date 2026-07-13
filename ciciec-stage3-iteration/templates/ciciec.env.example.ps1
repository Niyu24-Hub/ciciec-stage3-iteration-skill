# Required workspace configuration
$env:CICIEC_WORKSPACE = "C:\path\to\ciciec_workspace"
$env:CICIEC_SUBMISSION_REPO = "C:\path\to\submission-repository"
$env:CICIEC_SUBMISSION_REF = "submit/codex"
$env:CICIEC_CI_REF = $env:CICIEC_SUBMISSION_REF

# GitLab API configuration
$env:CICIEC_GITLAB_API_URL = "https://gitlab.example.com/api/v4"
$env:CICIEC_GITLAB_PROJECT_ID = "123"
$env:GITLAB_TOKEN = "replace-in-current-shell"

# Online judge configuration
$env:CICIEC_JUDGE_BASE_URL = "https://judge.example.com"
$env:CICIEC_STAGE3_LAB_ID = "optional-if-auto-discovery-works"
$env:CICIEC_JUDGE_USER = "replace-in-current-shell"
$env:CICIEC_JUDGE_PASSWORD = "replace-in-current-shell"

# Optional polling configuration
$env:CICIEC_CI_LIMIT = "30"
$env:CICIEC_CI_POLL_SECONDS = "30"
$env:CICIEC_CI_TIMEOUT_SECONDS = "3600"
