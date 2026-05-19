FROM nodered/node-red:latest

COPY --chown=node-red:node-red data/package.json /data/package.json
RUN cd /data && npm install --omit=dev

COPY --chown=node-red:node-red data/ /data/
