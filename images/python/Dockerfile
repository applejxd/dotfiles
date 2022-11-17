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

#---------#
# install #
#---------#

COPY requirements.txt "$HOME"
COPY environments.yml "$HOME"
RUN conda env create --file environments.yml

# ARG env_name=py38pip
# # Activate environment
# ENV CONDA_DEFAULT_ENV ${env_name}
# # Switch default environment
# RUN echo "conda activate ${env_name}" >> ~/.bashrc
# ENV PATH /opt/conda/envs/${env_name}/bin:$PATH

RUN apt-get clean && apt-get autoremove

CMD [ "/bin/bash" ]