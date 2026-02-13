import { api } from "./api";
import type { DirectionFrame, IntersectionFrames } from "../types";

const buildFallbackDirection = (index: number) => `camera-${index + 1}`;

const normalizeFrames = (frames: unknown): DirectionFrame[] => {
    if (!Array.isArray(frames)) return [];

    return frames.map((frame, index) => {
        if (typeof frame === "string") {
            return { direction: buildFallbackDirection(index), image: frame };
        }

        if (!frame || typeof frame !== "object") {
            return { direction: buildFallbackDirection(index), image: null };
        }

        const record = frame as Record<string, unknown>;
        const direction = typeof record.direction === "string"
            ? record.direction
            : buildFallbackDirection(index);
        const image = typeof record.image === "string" || record.image === null
            ? record.image
            : typeof record.base64 === "string"
                ? record.base64
                : typeof record.data === "string"
                    ? record.data
                    : null;

        return { direction, image };
    });
};

const normalizeIntersectionFrames = (data: unknown): IntersectionFrames => {
    if (!data || typeof data !== "object") {
        return { frames: [] };
    }

    const payload = data as Record<string, unknown>;
    let roads = Array.isArray(payload.roads)
        ? payload.roads.filter((road): road is string => typeof road === "string")
        : undefined;
    let intersectionId = typeof payload.intersection_id === "string"
        ? payload.intersection_id
        : undefined;
    let framesPayload: unknown = payload.frames ?? payload.images ?? payload.data;

    if (framesPayload && typeof framesPayload === "object" && !Array.isArray(framesPayload)) {
        const framesObject = framesPayload as Record<string, unknown>;
        if (!roads && Array.isArray(framesObject.roads)) {
            roads = framesObject.roads.filter((road): road is string => typeof road === "string");
        }
        if (!intersectionId && typeof framesObject.intersection_id === "string") {
            intersectionId = framesObject.intersection_id;
        }
        if (Array.isArray(framesObject.frames)) {
            framesPayload = framesObject.frames;
        }
    }

    if (!intersectionId && (typeof payload.intersections === "number" || typeof payload.intersections === "string")) {
        intersectionId = String(payload.intersections);
    }

    return {
        intersection_id: intersectionId,
        roads,
        frames: normalizeFrames(framesPayload),
    };
};

export const cameraService = {

    async getIntersection(params: { lat: number; lon: number }): Promise<IntersectionFrames> {
        const response = await api.get(`/traffic_light/frames`, { params });
        return normalizeIntersectionFrames(response.data);
    },

    getImageDataUrl(base64: string | null | undefined): string | null {
        if (!base64) return null;
        return `data:image/jpeg;base64,${base64}`;
    }
};
