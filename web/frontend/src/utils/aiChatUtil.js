import axios from "axios";

const aiApi = axios.create({
    baseURL: "/ai-api",
});

export async function sendQuery(query, farmId, houseId, farmName, houseName) {
    return aiApi.post("/api/v1/query", {
        query,
        farm_id: farmId,
        house_id: houseId,
        farm_name: farmName,
        house_name: houseName,
    });
}

export async function ragPerform(files, farmId) {
    const formData = new FormData();
    for (const file of files) {
        formData.append("files", file);
    }
    if (farmId) formData.append("farm_id", farmId);
    return aiApi.post("/api/v1/rag/perform", formData, {
        headers: {"Content-Type": "multipart/form-data"},
    });
}

export async function ragSave(messages, farmId, farmName, houseName) {
    return aiApi.post("/api/v1/rag/save", {
        messages,
        farm_id: farmId,
        farm_name: farmName,
        house_name: houseName,
    });
}
