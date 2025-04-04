#!/bin/bash

# Note that if any of these settings are changed, the base image will need to
# be rebuilt.

# NCEPlibs arguments
NCEPLIBS_PLATFORM=linux
NCEPLIBS_COMPILER=gnu

# ESMF arguments and environment variables
ESMF_OS=Linux
ESMF_COMPILER=gfortran
ESMF_SITE=default
ESMF_CC=

# FMS environment variables
FMS_CC=/usr/bin/mpicc
FMS_FC=/usr/bin/mpif90
FMS_LDFLAGS='-L/usr/lib'
FMS_LOG_DRIVER_FLAGS='--comments'
FMS_CPPFLAGS='-I/usr/include -Duse_LARGEFILE -DMAXFIELDMETHODS_=500 -DGFS_PHYS'
FMS_FCFLAGS='-fcray-pointer -Waliasing -ffree-line-length-none -fno-range-check -fdefault-real-8 -fdefault-double-8 -fopenmp'

# fv3gfs-fortran arguments
FV3GFS_PLATFORM=gnu_docker

# Python requirements environment variables
MPI4PY_CC=/usr/bin/mpicc
MPI4PY_MPICC=/usr/bin/mpicc

# Python wrapper environment variables
WRAPPER_CC='x86_64-linux-gnu-gcc -pthread'
WRAPPER_LDSHARED='x86_64-linux-gnu-gcc -pthread -shared'
