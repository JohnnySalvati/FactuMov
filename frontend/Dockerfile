# syntax=docker/dockerfile:1
#
# La imagen que sirve la SPA y, de paso, es el nginx que junta las dos mitades: el `dist`
# estático de acá y el backend JSON del contenedor de al lado, bajo `/api`.
#
# El prefijo `/api` lo inventa el proxy del dev server (ver `vite.config.ts`): el backend
# no sabe nada de él. En producción ese trabajo lo hace `nginx.conf`, que es exactamente
# lo que el comentario de `vite.config.ts` dice que el proxy imita.

# --- Etapa 1: el build de la SPA ---
# Corre acá y no en la máquina de nadie: así el deploy es un `git pull` + `up -d --build`
# y no depende de que alguien se acuerde de correr `npm run build` antes de pushear.
FROM node:22-alpine AS build

WORKDIR /app

# Igual que en el backend: primero los archivos de bloqueo, para que un cambio de código
# no reinstale node_modules.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# `npm run build` es `tsc -b && vite build`: si los tipos no cierran, el deploy se corta
# acá y no publica una SPA rota.
RUN npm run build

# --- Etapa 2: nginx ---
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
