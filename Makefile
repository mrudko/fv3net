.PHONY: clean data lint

#################################################################################
# GLOBALS                                                                       #
#################################################################################
VERSION ?= $(shell git rev-parse HEAD)
REGISTRY ?= us.gcr.io/vcm-ml
ENVIRONMENT_SCRIPTS = .environment-scripts
PROJECT_NAME ?= fv3net
CACHE_TAG =latest
BEAM_VERSION = 2.37.0
UBUNTU_IMAGE = ubuntu@sha256:9101220a875cee98b016668342c489ff0674f247f6ca20dfc91b91c0f28581ae
# prognostic base image is updated manually, not on every commit
PROGNOSTIC_BASE_VERSION = 1.1.0

# Explicitly mount the /fv3net/external/fv3gfs-fortran directory to prevent
# it from being overriden by the user's.  Historically we only interactively
# develop the Python dependencies of the images in fv3net.
DOCKER_INTERACTIVE_ARGS = \
	--tty \
	--interactive \
	-v $(shell pwd)/external:/fv3net/external \
	-v $(shell pwd)/workflows:/fv3net/workflows \
	-v $(shell pwd)/projects:/fv3net/projects \
	-v /fv3net/external/fv3gfs-fortran \
	--mount source=bash_history,target=/root/.bash_history \
	-e HISTFILE=/root/.bash_history/history

ifneq ("$(wildcard .env)","")
	DOCKER_INTERACTIVE_ARGS += --env-file=.env
endif

PROGNOSTIC_RUN_WORKDIR ?= /fv3net/workflows/prognostic_c48_run

IMAGES = fv3net post_process_run prognostic_run

.PHONY: build_images push_image run_integration_tests image_name_explicit
############################################################
# Docker Image Management
############################################################
# pattern rule for building docker images
build_image_%: ARGS
build_image_%:
	tools/docker_build_cached.sh $(REGISTRY)/$*:$(CACHE_TAG) \
		$(ARGS) \
		-f docker/$*/Dockerfile -t $(REGISTRY)/$*:$(VERSION) .

build_images: $(addprefix build_image_, $(IMAGES))
push_images: $(addprefix push_image_, $(IMAGES))

build_image_fv3fit: docker/fv3fit/requirements.txt
build_image_fv3fit_torch: docker/fv3fit_torch/requirements.txt
build_image_artifacts: docker/artifacts/requirements.txt

build_image_prognostic_run_base:
	tools/docker_build_cached.sh $(REGISTRY)/prognostic_run_base:$(CACHE_TAG) \
		-f docker/prognostic_run/base.Dockerfile -t $(REGISTRY)/prognostic_run_base:$(PROGNOSTIC_BASE_VERSION) \
		--target prognostic-run-base \
		--build-arg BASE_IMAGE=$(UBUNTU_IMAGE) .

build_image_prognostic_run: docker/prognostic_run/requirements.txt
ifneq ("$(docker images -q $(REGISTRY)/prognostic_run_base:$(PROGNOSTIC_BASE_VERSION) 2> /dev/null)","")
		docker pull $(REGISTRY)/prognostic_run_base:$(PROGNOSTIC_BASE_VERSION)
endif
	tools/docker_build_cached.sh $(REGISTRY)/prognostic_run:$(CACHE_TAG) \
		-f docker/prognostic_run/Dockerfile -t $(REGISTRY)/prognostic_run:$(VERSION) \
		--target prognostic-run \
		--build-arg BASE_IMAGE=$(REGISTRY)/prognostic_run_base:$(PROGNOSTIC_BASE_VERSION) .

build_image_prognostic_run_base_gpu:
	tools/docker_build_cached.sh $(REGISTRY)/prognostic_run_base_gpu:$(CACHE_TAG) \
		-f docker/prognostic_run/base.Dockerfile -t $(REGISTRY)/prognostic_run_base_gpu:$(PROGNOSTIC_BASE_VERSION) \
		--target prognostic-run-base \
		--build-arg BASE_IMAGE=nvidia/cuda:11.2.2-cudnn8-runtime-ubuntu20.04 .

build_image_prognostic_run_gpu: docker/prognostic_run/requirements.txt
ifneq ("$(docker images -q $(REGISTRY)/prognostic_run_base_gpu:$(PROGNOSTIC_BASE_VERSION) 2> /dev/null)","")
		docker pull $(REGISTRY)/prognostic_run_base_gpu:$(PROGNOSTIC_BASE_VERSION)
endif
	tools/docker_build_cached.sh $(REGISTRY)/prognostic_run_gpu:$(CACHE_TAG) \
		-f docker/prognostic_run/Dockerfile -t $(REGISTRY)/prognostic_run_gpu:$(VERSION) \
		--target prognostic-run \
		--build-arg BASE_IMAGE=$(REGISTRY)/prognostic_run_base_gpu:$(PROGNOSTIC_BASE_VERSION) .

build_image_dataflow: ARGS = --build-arg BEAM_VERSION=$(BEAM_VERSION)

image_test_dataflow: push_image_dataflow
	tools/docker-run \
		-w /tmp/dataflow \
		--entrypoint="pytest" \
		$(REGISTRY)/dataflow:$(VERSION) \
		tests/integration -s

image_test_emulation:
	tools/docker-run \
		--rm \
		-w /fv3net/external/emulation \
		$(REGISTRY)/prognostic_run:$(VERSION) pytest

image_test_prognostic_run: image_test_emulation
	tools/docker-run \
		--rm \
		-w /fv3net/workflows/prognostic_c48_run \
		$(REGISTRY)/prognostic_run:$(VERSION) pytest

image_test_%:
	echo "No tests specified"

push_image_%: build_image_%
	docker push $(REGISTRY)/$*:$(VERSION)

push_image_prognostic_run_base: build_image_prognostic_run_base
	docker push $(REGISTRY)/prognostic_run_base:$(PROGNOSTIC_BASE_VERSION)

push_image_prognostic_run_base_gpu: build_image_prognostic_run_base_gpu
	docker push $(REGISTRY)/prognostic_run_base_gpu:$(PROGNOSTIC_BASE_VERSION)

pull_image_%:
	docker pull $(REGISTRY)/$*:$(VERSION)

pull_image_prognostic_run_base:
	docker pull $(REGISTRY)/prognostic_run_base:$(PROGNOSTIC_BASE_VERSION)

pull_image_prognostic_run_base_gpu:
	docker pull $(REGISTRY)/prognostic_run_base_gpu:$(PROGNOSTIC_BASE_VERSION)

enter_emulation:
	PROGNOSTIC_RUN_WORKDIR=/fv3net/external/emulation $(MAKE) enter_prognostic_run

enter_%:
	tools/docker-run \
		--rm \
		$(DOCKER_INTERACTIVE_ARGS) \
		-w $(PROGNOSTIC_RUN_WORKDIR) \
		$(REGISTRY)/$*:$(VERSION) bash

############################################################
# Documentation (rules match "deploy_docs_%")
############################################################

## Deploy documentation to vulcanclimatemodeling.com
deploy_docs_%:
	@echo "Nothing to do."

## Deploy documentation for fv3net to vulcanclimatemodeling.com
deploy_docs_fv3net:
	mkdir -p fv3net_docs
	# use tar to grab already-built docs from inside the docker image and extract them to "./fv3net_docs"
	docker run $(REGISTRY)/fv3net:$(VERSION) tar -C fv3net_docs -c . | tar -C fv3net_docs -x
	gsutil -m rsync -R fv3net_docs gs://vulcanclimatemodeling-com-static/docs
	rm -rf fv3net_docs

## Deploy documentation for prognostic run to vulcanclimatemodeling.com
deploy_docs_prognostic_run:
	mkdir html
	# use tar to grab docs from inside the docker image and extract them to "./html"
	docker run $(REGISTRY)/prognostic_run tar -C docs/_build/html  -c . | tar -C html -x
	gsutil -m rsync -R html gs://vulcanclimatemodeling-com-static/docs/prognostic_c48_run
	rm -rf html

############################################################
# Testing
############################################################
run_integration_tests:
	./tests/end_to_end_integration/run_test.sh $(REGISTRY) $(VERSION)

test_prognostic_run_report:
	bash workflows/diagnostics/tests/prognostic/test_integration.sh

test_%: ARGS =
test_%:
	cd external/$* && tox -- $(ARGS)

test_unit: test_fv3kube test_vcm test_fv3fit test_artifacts
	coverage run -m pytest -m "not regression" --durations=20 $(ARGS)
	coverage combine \
		--append \
		external/fv3kube/.coverage \
		external/vcm/.coverage \
		external/fv3fit/.coverage \
		external/artifacts/.coverage

test_regression:
	pytest -vv -m regression -s $(ARGS)

test_dataflow:
	coverage run -m pytest -vv workflows/dataflow/tests/integration -s $(ARGS)

coverage_report:
	coverage report -i --omit='**/test_*.py',conftest.py,'external/fv3config/**.py','external/fv3gfs-fortran/**.py'

htmlcov:
	rm -rf $@
	coverage html -i --omit='**/test_*.py',conftest.py,'external/fv3config/**.py','external/fv3gfs-fortran/**.py'

test_argo:
	make -C workflows/argo/ test

## Make Dataset
.PHONY: data update_submodules create_environment overwrite_baseline_images

## Delete all compiled Python files
clean:
	find . -type f -name "*.py[co]" -delete
	find . -type d -name "__pycache__" -delete


## Set up python interpreter environment
update_submodules:
	git submodule sync --recursive
	git submodule update --init \
		external/fv3gfs-fortran \


############################################################
# Dependency Management
############################################################

lock_deps: lock_pip
	conda-lock -f environment.yml
	conda-lock render
	# external directories must be explicitly listed to avoid model requirements files which use locked versions

REQUIREMENTS = external/vcm/setup.py \
	pip-requirements.txt \
	external/fv3kube/setup.py \
	external/fv3fit/setup.py \
	external/loaders/setup.py \
    external/radiation/setup.py \
	external/*.requirements.in \
	workflows/post_process_run/requirements.txt \
	workflows/prognostic_c48_run/requirements.in \
	projects/microphysics/requirements.in

constraints.txt: $(REQUIREMENTS)
	docker run -ti --entrypoint="pip" apache/beam_python3.8_sdk:$(BEAM_VERSION) freeze \
		| sed 's/apache-beam.*/apache-beam=='$(BEAM_VERSION)'/' \
		| grep -v google-python-cloud-debugger \
		| grep -v atomicwrites \
		> .dataflow-versions.txt

	pip-compile  \
	--no-annotate \
	.dataflow-versions.txt \
	$^ \
	--output-file constraints.txt
	# remove extras in name: e.g. apache-beam[gcp] --> apache-beam
	sed -i.bak  's/\[.*\]//g' constraints.txt
	rm -f constraints.txt.bak .dataflow-versions.txt
	@echo "remember to update numpy version in external/vcm/pyproject.toml"

docker/prognostic_run/requirements.txt:
	cp constraints.txt docker/prognostic_run/requirements.txt
	# this will subset the needed dependencies from constraints.txt
	# while preserving the versions
	pip-compile --no-annotate \
		--output-file docker/prognostic_run/requirements.txt \
		external/artifacts/setup.py \
		external/fv3fit/setup.py \
		external/fv3gfs-fortran.requirements.in \
		external/fv3kube/setup.py \
		external/vcm/setup.py \
        external/radiation/setup.py \
		workflows/post_process_run/requirements.txt \
		workflows/prognostic_c48_run/requirements.in

docker/fv3fit/requirements.txt: external/fv3fit/setup.py external/loaders/setup.py external/vcm/setup.py
	cp constraints.txt $@
	# this will subset the needed dependencies from constraints.txt
	# while preserving the versions
	pip-compile --no-annotate \
		--output-file docker/fv3fit/requirements.txt \
		external/fv3fit/setup.py \
		external/loaders/setup.py \
		external/vcm/setup.py


docker/fv3fit_torch/requirements.txt: docker/fv3fit_torch/requirements.in external/fv3fit/setup.py external/loaders/setup.py external/vcm/setup.py
	cp constraints.txt $@
	# this will subset the needed dependencies from constraints.txt
	# while preserving the versions
	pip-compile --no-annotate \
		--output-file docker/fv3fit_torch/requirements.txt \
		external/fv3fit/setup.py \
		external/loaders/setup.py \
		external/vcm/setup.py \
		docker/fv3fit_torch/requirements.in

docker/artifacts/requirements.txt:
	cp -f constraints.txt $@
	# this will subset the needed dependencies from constraints.txt
	# while preserving the versions
	pip-compile --no-annotate \
		--output-file $@ \
		external/artifacts/setup.py \
		docker/artifacts/requirements.in

.PHONY: lock_pip constraints.txt
## Lock the pip dependencies of this repo
lock_pip: constraints.txt

## Install External Dependencies
install_deps:
	bash $(ENVIRONMENT_SCRIPTS)/build_environment.sh $(PROJECT_NAME)

## Install Local Packages for the "fv3net" environment
install_local_packages:
	bash $(ENVIRONMENT_SCRIPTS)/install_local_packages.sh $(PROJECT_NAME)

create_environment: update_submodules install_matplotlibrc
	bash $(ENVIRONMENT_SCRIPTS)/build_environment.sh $(PROJECT_NAME)
	bash $(ENVIRONMENT_SCRIPTS)/install_local_packages.sh $(PROJECT_NAME)

.PHONY: install_matplotlibrc
install_matplotlibrc:
	mkdir -p ${HOME}/.config/matplotlib
	rm -f ${HOME}/.config/matplotlib/matplotlibrc
	cp external/fv3viz/matplotlibrc ${HOME}/.config/matplotlib/

############################################################
# Linting
############################################################

setup-hooks:
	pip install -c constraints.txt pre-commit
	pre-commit install

typecheck:
	pre-commit run --all-files mypy

lint:
	pre-commit run --all-files
	@echo "LINTING SUCCESSFUL"

reformat:
	pre-commit run --all-files black

#################################################################################
# Self Documenting Commands                                                     #
#################################################################################

.DEFAULT_GOAL := help

# Inspired by <http://marmelab.com/blog/2016/02/29/auto-documented-makefile.html>
# sed script explained:
# /^##/:
# 	* save line in hold space
# 	* purge line
# 	* Loop:
# 		* append newline + line to hold space
# 		* go to next line
# 		* if line starts with doc comment, strip comment character off and loop
# 	* remove target prerequisites
# 	* append hold space (+ newline) to line
# 	* replace newline plus comments by `---`
# 	* print line
# Separate expressions are necessary because labels cannot be delimited by
# semicolon; see <http://stackoverflow.com/a/11799865/1968>
.PHONY: help
help:
	@echo "$$(tput bold)Available rules:$$(tput sgr0)"
	@echo
	@sed -n -e "/^## / { \
		h; \
		s/.*//; \
		:doc" \
		-e "H; \
		n; \
		s/^## //; \
		t doc" \
		-e "s/:.*//; \
		G; \
		s/\\n## /---/; \
		s/\\n/ /g; \
		p; \
	}" ${MAKEFILE_LIST} \
	| LC_ALL='C' sort --ignore-case \
	| awk -F '---' \
		-v ncol=$$(tput cols) \
		-v indent=19 \
		-v col_on="$$(tput setaf 6)" \
		-v col_off="$$(tput sgr0)" \
	'{ \
		printf "%s%*s%s ", col_on, -indent, $$1, col_off; \
		n = split($$2, words, " "); \
		line_length = ncol - indent; \
		for (i = 1; i <= n; i++) { \
			line_length -= length(words[i]) + 1; \
			if (line_length <= 0) { \
				line_length = ncol - indent - length(words[i]) - 1; \
				printf "\n%*s ", -indent, " "; \
			} \
			printf "%s ", words[i]; \
		} \
		printf "\n"; \
	}' \
	| more $(shell test $(shell uname) = Darwin && echo '--no-init --raw-control-chars')
