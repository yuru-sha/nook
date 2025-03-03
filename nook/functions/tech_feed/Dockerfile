FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.11

RUN yum install -y \
    gcc \
    python3.11 \
    libxml2-devel \
    libxslt-devel \
    python3-devel \
    python3-pip \
    python3-setuptools \
    python3-wheel

COPY . ${LAMBDA_TASK_ROOT}
WORKDIR ${LAMBDA_TASK_ROOT}

RUN pip install --upgrade pip \
    && pip install -r requirements.txt --target "${LAMBDA_TASK_ROOT}" \
    && pip install -r requirements-common.txt --target "${LAMBDA_TASK_ROOT}" \
    && pip install awslambdaric --target "${LAMBDA_TASK_ROOT}"

ENTRYPOINT [ "python", "-m", "awslambdaric" ]
CMD [ "tech_feed.lambda_handler" ]
