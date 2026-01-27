# Frontend Dockerfile for Traffic Light Optimization Web App
# Uses official bun image for fast builds and runtime

# Development stage
FROM oven/bun:1 AS dev

WORKDIR /app

# Copy package files for dependency caching
COPY package.json bun.lock ./

# Install dependencies
RUN bun install --frozen-lockfile

# Copy source files
COPY . .

# Expose Vite dev server port
EXPOSE 5173

# Run development server with host binding for Docker
CMD ["bun", "run", "dev", "--host", "0.0.0.0"]


# Production build stage
FROM oven/bun:1 AS build

WORKDIR /app

# Copy package files
COPY package.json bun.lock ./

# Install all dependencies (including dev for build)
RUN bun install --frozen-lockfile

# Copy source files
COPY . .

# Build the application
RUN bun run build


# Production stage - serve with nginx
FROM nginx:alpine AS production

# Copy built assets from build stage
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx config for SPA routing
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
