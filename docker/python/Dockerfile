FROM nvcr.io/nvidia/pytorch:22.12-py3
# Python 3.8.10 + CUDA 11.8 + PyTorch 1.14.0a0+410ce96

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

#---------#
# install #
#---------#

# for matplotlib GUI
RUN apt-get install -y python3-tk

COPY requirements.txt "$HOME"
RUN pip install -r requirements.txt

# ARG env_name=py38pip
# # Activate environment
# ENV CONDA_DEFAULT_ENV ${env_name}
# # Switch default environment
# RUN echo "conda activate ${env_name}" >> ~/.bashrc
# ENV PATH /opt/conda/envs/${env_name}/bin:$PATH

#--------#
# Open3D #
#--------#

RUN git clone https://github.com/isl-org/Open3D.git /workspace/open3d -b v0.16.1
RUN git clone https://github.com/isl-org/Open3D-ML.git /workspace/open3d-ml

# 依存関係のインストール
RUN yes | source /workspace/open3d/util/install_deps_ubuntu.sh
RUN pip install yapf

RUN mkdir -p /workspace/open3d/build
WORKDIR /workspace/open3d/build
RUN cmake -DBUILD_CUDA_MODULE=ON \
    -DGLIBCXX_USE_CXX11_ABI=OFF \
    -DBUILD_PYTORCH_OPS=ON \
    -DBUNDLE_OPEN3D_ML=ON \
    -DOPEN3D_ML_ROOT=/workspace/open3d-ml \
    ..
RUN make -j"$(nproc)" install-pip-package

RUN make install
WORKDIR /workspace
RUN rm -rf /workspace/open3d/build

RUN apt-get clean && apt-get autoremove

CMD [ "/bin/bash" ]