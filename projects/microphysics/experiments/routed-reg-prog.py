import sys

sys.path.insert(0, "../argo")

from end_to_end import (
    PrognosticJob,
    load_yaml,
    submit_jobs,
)  # noqa: E402


name = "gscond-routed-reg-v3-prog-v2"
image = "e7e102888890949b968cf532f020fa56ff8d96fe"


config = load_yaml("../configs/gscond-only.yaml")
job = PrognosticJob(name=name, image_tag=image, config=config,)
jobs = [job]
submit_jobs(jobs, f"routed-regression")
