FROM nginx:alpine

WORKDIR /usr/share/nginx/html

# 清理默认静态文件
RUN rm -rf ./*

# 拷贝前端静态资源
COPY . .

EXPOSE 80

