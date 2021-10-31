FROM python:3.9

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /arbitrage_strategy

COPY ./arbitrage_strategy/pyproject.toml ./arbitrage_strategy/poetry.lock* /arbitrage_strategy/

# Install Poetry
RUN pip3 install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-root --no-dev

COPY ./arbitrage_strategy /arbitrage_strategy
