# 빌드 단계는 빌드하는 머신 아키텍처로, 실행 단계만 대상(arm64) 아키텍처로
FROM --platform=$BUILDPLATFORM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
