import React, { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Col, List, Row, Space, Statistic, Table, Tag, Tooltip, Spin } from "antd";
import dayjs from "dayjs";
import { fetchStats, fetchDecisions, fetchEvents, fetchTrades } from "../api";

/**
 * @typedef {Object} OverviewStats
 * @property {number} totalSignalsToday
 * @property {number} totalTradesToday
 * @property {number} winRateToday
 * @property {number} avgRrToday
 * @property {number} openPositions
 * @property {number} currentRisk
 */

/**
 * @typedef {Object} SymbolStats
 * @property {string} symbol
 * @property {number} signalsToday
 * @property {number} tradesToday
 * @property {number} winRateToday
 * @property {number} pnlToday
 * @property {string} currentPosition
 * @property {string} runId
 */

/**
 * @typedef {Object} DecisionSummary
 * @property {string|number} id
 * @property {string} time
 * @property {string} symbol
 * @property {string} decisionType
 * @property {string} summary
 */

/**
 * @typedef {Object} EventSummary
 * @property {string|number} id
 * @property {"INFO"|"WARNING"|"ERROR"} level
 * @property {string} time
 * @property {string} eventType
 * @property {string} message
 */

const levelColor = {
  INFO: "blue",
  WARNING: "gold",
  ERROR: "red",
};

function OverviewCards({ overview }) {
  const cards = [
    { title: "今日信号数", value: overview?.totalSignalsToday ?? 0 },
    { title: "今日已执行交易数", value: overview?.totalTradesToday ?? 0 },
    { title: "今日胜率(%)", value: overview?.winRateToday ?? 0 },
    { title: "今日平均 RR", value: overview?.avgRrToday ?? 0 },
    { title: "当前总持仓数量", value: overview?.openPositions ?? 0 },
    { title: "当前总风险", value: overview?.currentRisk ?? 0 },
  ];
  return (
    <Row gutter={16}>
      {cards.map((item) => (
        <Col span={4} key={item.title}>
          <Card>
            <Statistic title={item.title} value={item.value} />
          </Card>
        </Col>
      ))}
    </Row>
  );
}

function SymbolTable({ symbols, onViewLogs }) {
  const columns = useMemo(
    () => [
      { title: "品种", dataIndex: "symbol", width: 120, ellipsis: true },
      { title: "今日信号数", dataIndex: "signalsToday", width: 120, align: "center" },
      { title: "今日成交数", dataIndex: "tradesToday", width: 120, align: "center" },
      { title: "今日胜率(%)", dataIndex: "winRateToday", width: 120, align: "center" },
      {
        title: "今日PNL",
        dataIndex: "pnlToday",
        width: 120,
        align: "center",
        render: (val) => (
          <span style={{ color: val > 0 ? "#52c41a" : val < 0 ? "#ff4d4f" : undefined }}>{val}</span>
        ),
      },
      {
        title: "当前持仓",
        dataIndex: "currentPosition",
        width: 160,
        ellipsis: true,
      },
      { title: "run_id", dataIndex: "runId", width: 200, ellipsis: true },
      {
        title: "操作",
        width: 120,
        render: (_, record) => (
          <Button type="link" onClick={() => onViewLogs?.(record.symbol, record.runId)}>
            查看日志
          </Button>
        ),
      },
    ],
    [onViewLogs]
  );

  return (
    <Card title="按品种统计">
      <Table
        dataSource={symbols}
        columns={columns}
        rowKey="symbol"
        pagination={false}
        scroll={{ x: 1000 }}
      />
    </Card>
  );
}

function RecentDecisions({ items }) {
  return (
    <Card title="最近 AI 决策">
      <List
        dataSource={items}
        renderItem={(item) => (
          <List.Item key={item.id}>
            <List.Item.Meta
              title={
                <Space>
                  <span>{item.time}</span>
                  <Tag>{item.symbol}</Tag>
                  <Tag color="blue">{item.decisionType}</Tag>
                </Space>
              }
              description={
                <Tooltip title={item.summary}>
                  <span className="nowrap-cell">{item.summary}</span>
                </Tooltip>
              }
            />
          </List.Item>
        )}
      />
    </Card>
  );
}

function RecentEvents({ items }) {
  return (
    <Card title="最近系统事件">
      <List
        dataSource={items}
        renderItem={(item) => (
          <List.Item key={item.id}>
            <List.Item.Meta
              title={
                <Space>
                  <span>{item.time}</span>
                  <Tag color={levelColor[item.level] || "default"}>{item.level}</Tag>
                  <Tag>{item.eventType}</Tag>
                </Space>
              }
              description={
                <Tooltip title={item.message}>
                  <span className="nowrap-cell">{item.message}</span>
                </Tooltip>
              }
            />
          </List.Item>
        )}
      />
    </Card>
  );
}

export default function Dashboard({ onNavigateToLogs }) {
  const [overview, setOverview] = useState(/** @type {OverviewStats | null} */ (null));
  const [symbolStats, setSymbolStats] = useState(/** @type {SymbolStats[]} */ ([]));
  const [decisions, setDecisions] = useState(/** @type {DecisionSummary[]} */ ([]));
  const [events, setEvents] = useState(/** @type {EventSummary[]} */ ([]));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadData = async () => {
    const start = dayjs().startOf("day").toISOString();
    const end = dayjs().toISOString();
    setLoading(true);
    try {
      const [statsRes, decisionsRes, eventsRes, tradesRes] = await Promise.all([
        fetchStats({ start, end }),
        fetchDecisions({ start, end, limit: 10, offset: 0 }),
        fetchEvents({ start, end, limit: 10, offset: 0 }),
        fetchTrades({ start, end, limit: 100, offset: 0 }).catch(() => ({ items: [], total: 0 })),
      ]);

      setOverview({
        totalSignalsToday: statsRes?.total ?? 0,
        totalTradesToday: tradesRes?.total ?? 0,
        winRateToday: 0, // TODO: 等后端提供胜率/绩效接口
        avgRrToday: 0, // TODO: 等后端提供 RR 统计
        openPositions: 0, // TODO: 待接 position 接口
        currentRisk: 0, // TODO: 待接风险聚合
      });

      const symbols =
        statsRes?.by_symbol && typeof statsRes.by_symbol === "object"
          ? Object.entries(statsRes.by_symbol).map(([sym, count]) => ({
              symbol: sym,
              signalsToday: count,
              tradesToday: 0, // TODO: 结合 /api/trades 按 symbol 聚合
              winRateToday: 0,
              pnlToday: 0,
              currentPosition: "无持仓",
              runId: statsRes?.by_run_id ? Object.keys(statsRes.by_run_id)[0] || "-" : "-",
            }))
          : [];
      setSymbolStats(symbols);

      const decisionItems =
        decisionsRes?.items?.map((d) => ({
          id: d.id,
          time: d.created_at,
          symbol: d.symbol,
          decisionType: d.decision_type,
          summary: d.reason_snippet || "",
        })) || [];
      setDecisions(decisionItems);

      const eventItems =
        eventsRes?.items?.map((ev) => ({
          id: ev.id,
          time: ev.created_at,
          level: (ev.severity || "INFO").toUpperCase(),
          eventType: ev.event_type,
          message: ev.description || "",
        })) || [];
      setEvents(eventItems);
      setError("");
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  return (
    <Spin spinning={loading}>
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        {error && <Alert type="error" message={error} showIcon />}
        <OverviewCards overview={overview} />
        <SymbolTable symbols={symbolStats} onViewLogs={onNavigateToLogs} />
        <Row gutter={16}>
          <Col span={12}>
            <RecentDecisions items={decisions} />
          </Col>
          <Col span={12}>
            <RecentEvents items={events} />
          </Col>
        </Row>
      </Space>
    </Spin>
  );
}
