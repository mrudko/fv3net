# syntax=docker/dockerfile:experimental
FROM ubuntu:20.04 as bld

ENV DEBIAN_FRONTEND="noninteractive"

RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    git \
    libblas-dev \
    liblapack-dev \
    libnetcdf-dev \
    netcdf-bin \
    libnetcdff-dev \
    libmpich-dev \
    autoconf \
    perl \
    make \
    rsync \
    python3-dev \
    python3-pip

# install FRE-NCtools including fregrid. Ideally we would download a
# tarball of the latest versioned tag (v2.18.0) but v2.18.0 fails
# to build whereas this more recent commit is successful.
RUN git config --global http.sslverify false && \
    git clone https://github.com/NOAA-GFDL/FRE-NCtools.git && \
    cd FRE-NCtools && \
    git checkout f5d700467f100b63bf5bf92d69c76be989dd2924 && \
    export CFLAGS=-Wno-traditional NETCDF_LDFLAGS=-lm && \
    autoreconf -i && ./configure && make && make install && \
    cd .. && rm -r FRE-NCtools

# install gcloud
RUN apt-get update && apt-get install -y  apt-transport-https ca-certificates gnupg curl gettext

RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list &&\
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key --keyring /usr/share/keyrings/cloud.google.gpg add -

RUN apt-get update && apt-get install -y google-cloud-sdk
RUN gcloud config set project vcm-ml

# install python dependencies
RUN pip3 install pytest
COPY workflows/post_process_run/requirements.txt /tmp/requirements.txt
COPY constraints.txt /tmp/constraints.txt
RUN pip3 install -c /tmp/constraints.txt -r /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt /tmp/constraints.txt

# install python package
COPY workflows/post_process_run /post_process_run
RUN pip3 install /post_process_run --no-deps --no-cache-dir

FROM bld as test

# run tests
WORKDIR /post_process_run
ENV GOOGLE_APPLICATION_CREDENTIALS /tmp/key.json
RUN --mount=type=secret,id=gcp,dst=/tmp/key.json \
    gcloud auth activate-service-account --key-file /tmp/key.json && \
    mkdir -p /tmp/mosaic_data && \
    gsutil -m cp -r gs://vcm-ml-raw/2020-11-12-gridspec-orography-and-mosaic-data/C48 /tmp/mosaic_data
RUN ["bash", "-o", "pipefail", "-c", "pytest -vv | tee /tmp/test-results.txt"]

FROM bld
# Copy results from test stage to ensure docker buildkit executes it
COPY --from=test /tmp/test-results.txt .

ARG COMMIT_SHA_ARG
ENV COMMIT_SHA=$COMMIT_SHA_ARG
