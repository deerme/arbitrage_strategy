FROM python:3.10

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /arbitrage_strategy

COPY ./pyproject.toml ./poetry.lock* /arbitrage_strategy/

# Install Poetry
RUN pip3 install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-root --no-dev

COPY ./arbitrage_strategy /arbitrage_strategy
