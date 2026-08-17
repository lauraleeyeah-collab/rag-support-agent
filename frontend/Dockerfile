FROM node:20-alpine

WORKDIR /app

COPY package.json .
RUN npm install --registry=https://registry.npmmirror.com

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
