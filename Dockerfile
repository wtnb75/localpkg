FROM python:3-alpine AS build
COPY ./ /app
RUN --mount=type=cache,target=/root/.cache cd /app && pip install build && python -m build -w
RUN cd /app/dist && pip wheel -r ../requirements.txt

FROM python:3-alpine
ENV PYTHONDONTWRITEBYTECODE=1
RUN apk add --no-cache rpm file findutils coreutils binutils fakeroot openssh git dpkg pacman abuild python3 build-base
RUN adduser pkg -G abuild -D
RUN ln -sf /bin/true /usr/bin/debugedit
RUN pacman -D -kk
COPY --from=build /app/dist/*.whl /dist/
RUN --mount=type=cache,target=/root/.cache pip install --no-compile /dist/*.whl
USER pkg
ENTRYPOINT ["localpkg"]
