show:
	cat Makefile

########
# HTTP #
########

# http://localhost:5888/?token=...
tf:
	docker run -it --rm --gpus all -p 58888:8888 \
	tensorflow/tensorflow:latest-gpu-py3-jupyter

# http://localhost:58889
rapids:
	docker run -d --rm --gpus all \
	-p 58889:8888 -p 8787:8787 -p 8786:8786 \
	-v $$HOME:/rapids/notebooks/mnt \
	rapidsai/rapidsai-core:22.02-cuda11.5-runtime-ubuntu20.04-py3.9

# http://localhost:58890
ros:
	docker run -d --rm -p 58890:80 --shm-size=512m \
	-v $$HOME:/root/mnt \
	tiryoh/ros-desktop-vnc:melodic

#############
# CUDA Test #
#############

cuda_test:
	docker run --rm --gpus all \
	nvcr.io/nvidia/k8s/cuda-sample:nbody nbody -gpu -benchmark

tf_simple:
	docker run -it --rm --gpus all --shm-size=1g --ulimit memlock=-1 --ulimit stack=67108864 \
	nvcr.io/nvidia/tensorflow:20.03-tf2-py3
