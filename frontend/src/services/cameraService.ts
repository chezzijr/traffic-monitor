import { api } from "./api";
import type { DirectionFrame, IntersectionFrames } from "../types";

const normalizeFrames = (frames: unknown): DirectionFrame[] => {
    if (!Array.isArray(frames)) return [];

    return frames.map((frame) => {
        if (!frame || typeof frame !== "object") {
            return { image: null };
        }

        const record = frame as Record<string, unknown>;

        const number =
            typeof record.number === "number"
                ? record.number
                : undefined;

        const image =
            typeof record.image === "string"
                ? record.image
                : typeof record.base64 === "string"
                    ? record.base64
                    : typeof record.data === "string"
                        ? record.data
                        : null;

        return { number, image };
    });
};

const normalizeIntersectionFrames = (data: unknown): IntersectionFrames => {
    if (!data || typeof data !== "object") {
        return { frames: [] };
    }

    const payload = data as Record<string, unknown>;

    const roads = Array.isArray(payload.roads)
        ? payload.roads.filter((road): road is string => typeof road === "string")
        : undefined;

    const intersectionId =
        typeof payload.intersection_id === "string"
            ? payload.intersection_id
            : undefined;

    const framesPayload =
        payload.frames ?? payload.images ?? payload.data;

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