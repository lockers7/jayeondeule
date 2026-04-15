import React, { useState, useRef, useCallback, useEffect } from "react";
import {
    Card,
    Form,
    Button,
    Row,
    Col,
} from "react-bootstrap";
import {
    useQuery,
    useMutation, useQueryClient,
} from "@tanstack/react-query";
import { createMemo, deleteMemo, getMemos, updateMemo } from "../../utils/memoUtil.js";
import AlertModal from "../common/AlertModal.jsx";
import MemoList from "./MemoList.jsx";

import { CROP_STAT_OPTIONS } from "./cropStatOptions.js";
import "./MemoDashboard.css";

export default function MemoDashboard({ farmId, houseId, houses = [], farmName = "" }) {
    const queryClient = useQueryClient();
    const [memoHouseId, setMemoHouseId] = useState(houseId);
    const [newMemo, setNewMemo] = useState("");
    const [cropStat, setCropStat] = useState(0);
    const [editingId, setEditingId] = useState(null);
    const [editText, setEditText] = useState("");
    const [page, setPage] = useState(0);
    const [memos, setMemos] = useState([]);
    const [hasMore, setHasMore] = useState(true);
    const [show, setShow] = useState(false);
    const observer = useRef();
    const pageSize = 10;

    // 외부 재배사 선택 변경 시 메모 콤보도 동기화
    useEffect(() => {
        setMemoHouseId(houseId);
    }, [houseId]);

    // 메모 조회 (메모 콤보에서 선택한 재배사 기준)
    const { data, isLoading, refetch } = useQuery({
        queryKey: ["memos", farmId, memoHouseId, page],
        queryFn: async () => {
            const res = await getMemos(farmId, memoHouseId, page, pageSize);
            return res.data.content || [];
        },
        enabled: !!farmId && memoHouseId != null,
        keepPreviousData: true,
    });

    // 새 데이터 들어올 때 합치기
    useEffect(() => {
        if (data) {
            if (page === 0) {
                setMemos(data);
            } else {
                setMemos((prev) => [...prev, ...data]);
            }
            if (data.length < pageSize) setHasMore(false);
        } else if (page === 0) {
            setMemos([]);
        }
    }, [data]);

    useEffect(() => {
        setPage(0);
        setHasMore(true);
        queryClient.invalidateQueries(["memos", farmId, memoHouseId]);
    }, [farmId, memoHouseId, queryClient])

    // 무한 스크롤
    const lastMemoRef = useCallback(
        (node) => {
            if (isLoading) return;
            if (observer.current) observer.current.disconnect();
            observer.current = new IntersectionObserver((entries) => {
                if (entries[0].isIntersecting && hasMore) {
                    setPage((prev) => prev + 1);
                }
            });
            if (node) observer.current.observe(node);
        },
        [isLoading, hasMore]
    );

    // 메모 추가
    const addMemoMutation = useMutation({
        mutationFn: async () =>
            await createMemo(farmId, memoHouseId, { memo: newMemo, cropStat }),
        onSuccess: () => {
            setMemos([]);
            setPage(0);
            setHasMore(true);
            queryClient.invalidateQueries(["memos", farmId, memoHouseId]);
            setNewMemo("");
            setCropStat(0);
        },
    });

    // 메모 수정
    const updateMemoMutation = useMutation({
        mutationFn: async (content) =>
            await updateMemo(farmId, memoHouseId, content),
        onSuccess: () => {
            setEditingId(null);
            setEditText("");
            setMemos([]);
            setPage(0);
            setHasMore(true);
            queryClient.invalidateQueries(["memos", farmId, memoHouseId]);
            setNewMemo("");
        },
    });

    // 메모 삭제
    const deleteMemoMutation = useMutation({
        mutationFn: async (recdDttm) =>
            await deleteMemo(farmId, memoHouseId, recdDttm),
        onSuccess: (_, memoId) => {
            setMemos((prev) => prev.filter((m) => m.recdDttm !== memoId));
        },
    });

    const handleAddMemo = (e) => {
        e.preventDefault();
        if (!newMemo.trim()) return;
        addMemoMutation.mutate();
    };

    const handleEditMemo = (content) => {
        if (!editText.trim()) return;
        updateMemoMutation.mutate(content);
    };

    const handleDeleteMemo = (recdDttm) => {
        setEditingId(recdDttm);
        setShow(true);
    };

    function handleDelete() {
        deleteMemoMutation.mutate(editingId);
        setShow(false);
        setEditingId(null);
    }

    return (
        <Row>
            <Col md={12}>
                {/* 새 메모 작성 */}
                <Card className="mt-3 mb-3 p-3">
                    <Form onSubmit={handleAddMemo}>
                        <div style={{ display: "flex", gap: "1em", alignItems: "stretch" }}>
                            {houses.length > 0 && (
                                <div style={{ flex: "0 0 9em", display: "flex", flexDirection: "column", gap: "0.3em" }}>
                                    <Form.Label style={{ margin: 0, fontSize: "1.07rem", fontWeight: "bold", textAlign: "center" }}>
                                        재배사
                                    </Form.Label>
                                    <Form.Select
                                        value={memoHouseId}
                                        onChange={(e) => {
                                            setMemoHouseId(Number(e.target.value));
                                        }}
                                        className="memo-input-border"
                                        style={{ flex: "1" }}
                                    >
                                        {houses.map(h => (
                                            <option key={h.housId} value={h.housId}>
                                                {h.housId === 0 ? `${farmName} 재배사공통` : h.housName}
                                            </option>
                                        ))}
                                    </Form.Select>
                                </div>
                            )}
                            <div style={{ flex: "0 0 7em", display: "flex", flexDirection: "column", gap: "0.3em" }}>
                                <Form.Label style={{ margin: 0, fontSize: "1.07rem", fontWeight: "bold", textAlign: "center" }}>
                                    생육 상태
                                </Form.Label>
                                <Form.Select
                                    value={cropStat}
                                    onChange={(e) => setCropStat(Number(e.target.value))}
                                    className="memo-input-border"
                                    style={{ flex: "1" }}
                                >
                                    {CROP_STAT_OPTIONS.map(opt => (
                                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                                    ))}
                                </Form.Select>
                            </div>
                            <Form.Control
                                as="textarea"
                                rows={2}
                                placeholder="새 메모 입력... (Shift+Enter: 줄바꿈, Enter: 전송)"
                                value={newMemo}
                                onChange={(e) => setNewMemo(e.target.value)}
                                className="memo-input-border"
                                style={{ flex: "1 1 auto" }}
                                onKeyDown={(e) => {
                                    if (e.key === "Enter" && !e.shiftKey) {
                                        e.preventDefault();
                                        handleAddMemo(e);
                                    }
                                }}
                            />
                            <Button type="submit" variant="success" style={{ flex: "0 0 auto" }}>
                                추가
                            </Button>
                        </div>
                    </Form>
                </Card>

                {/* 메모 리스트 */}
                <MemoList
                    memos={memos}
                    lastMemoRef={lastMemoRef}
                    editText={editText}
                    setEditText={setEditText}
                    editingId={editingId}
                    setEditingId={setEditingId}
                    handleDeleteMemo={handleDeleteMemo}
                    handleEditMemo={handleEditMemo}
                    isLoading={isLoading}
                    hasMore={hasMore}
                />
            </Col>
            <AlertModal
                show={show}
                hideModalFunc={() => setShow(false)}
                onClickFunc={() => handleDelete()}
                title="정말 삭제하시겠습니까?"
                body="삭제 후 복구가 불가능할 수 있습니다."
                variant="danger"
                buttonMsg="삭제"
            />
        </Row>
    );
}