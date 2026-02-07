import { api } from './api';
import type { CameraResponse, CameraSnapshot, CameraStreamInfo } from '../types';

export const cameraService = {
    // Get camera data (snapshot + stream info) for an intersection
    async getCameraData(intersectionId: string): Promise<CameraResponse> {
        const response = await api.get<CameraResponse>(`/camera/intersections/${intersectionId}`);
        return response.data;
    },

    // Get recent snapshots for an intersection
    async getSnapshots(intersectionId: string, limit: number = 10): Promise<CameraSnapshot[]> {
        const response = await api.get<CameraSnapshot[]>(
            `/camera/snapshots/${intersectionId}`,
            { params: { limit } }
        );
        return response.data;
    },

    // Upload a snapshot file
    async uploadSnapshot(
        intersectionId: string,
        file: File,
        step: number = 0
    ): Promise<CameraSnapshot> {
        const formData = new FormData();
        formData.append('file', file);

        const response = await api.post<CameraSnapshot>(
            `/camera/snapshots/${intersectionId}`,
            formData,
            {
                params: { step },
                headers: { 'Content-Type': 'multipart/form-data' },
            }
        );
        return response.data;
    },

    // Set stream URL for an intersection
    async setStreamUrl(intersectionId: string, streamUrl: string | null): Promise<CameraStreamInfo> {
        const response = await api.post<CameraStreamInfo>(
            `/camera/stream/${intersectionId}`,
            {},
            { params: { stream_url: streamUrl } }
        );
        return response.data;
    },

    // Get stream info for an intersection
    async getStreamInfo(intersectionId: string): Promise<CameraStreamInfo> {
        const response = await api.get<CameraStreamInfo>(`/camera/stream/${intersectionId}`);
        return response.data;
    },

    // Get specific snapshot by ID
    async getSnapshot(intersectionId: string, snapshotId: string): Promise<CameraSnapshot> {
        const response = await api.get<CameraSnapshot>(
            `/camera/snapshot/${intersectionId}/${snapshotId}`
        );
        return response.data;
    },

    // List all cameras
    async listAllCameras(): Promise<Record<string, CameraStreamInfo>> {
        const response = await api.get<Record<string, CameraStreamInfo>>('/camera/list');
        return response.data;
    },

    // Get image data URL from base64
    getImageDataUrl(snapshot: CameraSnapshot): string {
        return `data:${snapshot.media_type};base64,${snapshot.snapshot_data}`;
    },

    // Check if snapshot is video
    isVideo(snapshot: CameraSnapshot): boolean {
        return snapshot.media_type.startsWith('video/');
    },

    // Check if snapshot is image
    isImage(snapshot: CameraSnapshot): boolean {
        return snapshot.media_type.startsWith('image/');
    },
};
