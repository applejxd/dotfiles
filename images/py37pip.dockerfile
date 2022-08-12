FROM condaforge/miniforge3:latest

WORKDIR /root
RUN apt-get update && apt-get upgrade -y

# ロケール 入力を省略
RUN DEBIAN_FRONTEND="noninteractive" apt-get install -y tzdata
ENV TZ=Asia/Tokyo

# ロケール設定
RUN apt-get install -y locales fonts-takao && locale-gen ja_JP.UTF-8
ENV LANG=ja_JP.UTF-8
ENV LANGUAGE=ja_JP:ja
ENV LC_ALL=ja_JP.UTF-8
RUN localedef -f UTF-8 -i ja_JP ja_JP.utf8

##############
# Python 3.7 #
##############

ARG env_name=myenv
RUN conda create -yn ${env_name} python=3.7
# Activate environment
ENV CONDA_DEFAULT_ENV ${env_name}
# Switch default environment
RUN echo "conda activate ${env_name}" >> ~/.bashrc
ENV PATH /opt/conda/envs/${env_name}/bin:$PATH

# install pip
RUN conda install pip
RUN pip install --upgrade pip

#######
# pip #
#######

RUN pip install numpy pandas \
    matplotlib japanize-matplotlib \
    scipy dask numba \
    opencv-python open3d laspy[lazrs,laszip] \
    pycaret[full]

RUN apt-get clean && apt-get autoremove