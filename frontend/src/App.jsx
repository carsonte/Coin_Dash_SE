import React, { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Collapse,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Grid,
  Input,
  Layout,
  Message,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Tooltip,
} from "@arco-design/web-react";
import { IconSearch } from "@arco-design/web-react/icon";
import dayjs from "dayjs";
import "./table.css";
import {
  fetchStats,
  fetchDecisions,
  fetchDecisionDetail,
  fetchEventEnum,
  fetchEvents,
} from "./api";

const { Row, Col } = Grid;
const { RangePicker } = DatePicker;

function useDateRange(defaultHours = 24) {
  const [range, setRange] = useState(() => {
    const end = dayjs();
    const start = end.subtract(defaultHours, "hour");
    return [start, end];
  });
  return [range, setRange];
}

function JsonBlock({ title, obj }) {
  if (!obj) return null;
  return (
    <Collapse defaultActiveKey={title}>
      <Collapse.Item header={title} name={title}>
        <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(obj, null, 2)}</pre>
      </Collapse.Item>
    </Collapse>
  );
}

function DecisionTable({ filters }) {
  const [data, setData] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState(null);
  const [page, setPage] = useState({ current: 1, pageSize: 20 });

  const load = async (pg = page) => {
    if (!filters.start || !filters.end) return;
    setLoading(true);
    try {
      const res = await fetchDecisions({
        start: filters.start,
        end: filters.end,
        symbol: filters.symbol || undefined,
        run_id: filters.run_id || undefined,
        decision_type: filters.decision_type || undefined,
        keyword: filters.keyword || undefined,
        limit: pg.pageSize,
        offset: (pg.current - 1) * pg.pageSize,
      });
      setData(res.items || []);
      setTotal(res.total || 0);
    } catch (err) {
      Message.error(`决策列表获取失败：${err}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load({ current: 1, pageSize: page.pageSize });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.start, filters.end, filters.symbol, filters.run_id, filters.decision_type, filters.keyword]);

  const columns = useMemo(
    () => [
      { title: "时间", dataIndex: "created_at", width: 160, ellipsis: true, align: "center" },
      { title: "品种", dataIndex: "symbol", width: 100, ellipsis: true, align: "center" },
      { title: "类型", dataIndex: "decision_type", width: 100, ellipsis: true, align: "center" },
      { title: "置信度", dataIndex: "confidence", width: 80, ellipsis: true, align: "center" },
      { title: "Tokens", dataIndex: "tokens_used", width: 120, ellipsis: true, align: "center" },
      { title: "延迟(ms)", dataIndex: "latency_ms", width: 120, ellipsis: true, align: "center" },
      {
        title: "理由摘要",
        dataIndex: "reason_snippet",
        width: 300,
        ellipsis: true,
        render: (val) => (
          <Tooltip content={val || ""} position="top">
            <span className="nowrap-cell">{val || ""}</span>
          </Tooltip>
        ),
      },
      { title: "run_id", dataIndex: "run_id", width: 120, ellipsis: true, align: "center" },
      {
        title: "操作",
        width: 80,
        align: "center",
        ellipsis: true,
        render: (_, record) => (
          <Button
            type="text"
            size="small"
            onClick={async () => {
              try {
                const res = await fetchDecisionDetail(record.id);
                setDetail(res);
              } catch (err) {
                Message.error(`获取详情失败：${err}`);
              }
            }}
          >
            详情
          </Button>
        ),
      },
    ],
    []
  );

  const pagination = {
    current: page.current,
    pageSize: page.pageSize,
    total,
    onChange: (current, pageSize) => {
      const newPg = { current, pageSize };
      setPage(newPg);
      load(newPg);
    },
  };

  return (
    <>
      <Table
        loading={loading}
        data={data}
        columns={columns}
        pagination={pagination}
        rowKey="id"
        scroll={{ y: 420, x: 1300 }}
        noDataElement={<Empty description="暂无数据" />}
        border={false}
        tableLayout="fixed"
        className="logs-table"
        rowClassName={() => "log-row"}
      />
      <Drawer
        title="决策详情"
        width={720}
        visible={!!detail}
        onCancel={() => setDetail(null)}
        unmountOnExit
      >
        {detail ? (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Descriptions column={2} data={[
              { label: "run_id", value: detail.run_id },
              { label: "symbol", value: detail.symbol },
              { label: "decision_type", value: detail.decision_type },
              { label: "confidence", value: detail.confidence },
              { label: "tokens", value: detail.tokens_used },
              { label: "latency", value: detail.latency_ms },
              { label: "时间", value: detail.created_at },
            ]} />
            <JsonBlock title="payload" obj={detail.payload} />
            <JsonBlock title="result" obj={detail.result} />
          </Space>
        ) : (
          <Spin />
        )}
      </Drawer>
    </>
  );
}

function EventList({ filters, eventTypes }) {
  const [data, setData] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState({ current: 1, pageSize: 20 });

  const load = async (pg = page) => {
    if (!filters.start || !filters.end) return;
    setLoading(true);
    try {
      const res = await fetchEvents({
        start: filters.start,
        end: filters.end,
        event_type: filters.event_type || undefined,
        run_id: filters.run_id || undefined,
        keyword: filters.keyword || undefined,
        limit: pg.pageSize,
        offset: (pg.current - 1) * pg.pageSize,
      });
      setData(res.items || []);
      setTotal(res.total || 0);
    } catch (err) {
      Message.error(`事件列表获取失败：${err}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load({ current: 1, pageSize: page.pageSize });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.start, filters.end, filters.event_type, filters.run_id, filters.keyword]);

  const pagination = {
    current: page.current,
    pageSize: page.pageSize,
    total,
    onChange: (current, pageSize) => {
      const newPg = { current, pageSize };
      setPage(newPg);
      load(newPg);
    },
  };

    return (
    <Table
      loading={loading}
      data={data}
      rowKey="id"
      columns={[
        { title: "时间", dataIndex: "created_at", width: 160, ellipsis: true, align: "center" },
        { title: "事件", dataIndex: "event_type", width: 140, ellipsis: true, align: "center", render: (v) => <Tag color="arcoblue">{v}</Tag> },
        { title: "级别", dataIndex: "severity", width: 80, ellipsis: true, align: "center" },
        {
          title: "描述",
          dataIndex: "description",
          width: 300,
          ellipsis: true,
          render: (v) => (
            <Tooltip content={v || ""} position="top">
              <span className="nowrap-cell">{v || ""}</span>
            </Tooltip>
          ),
        },
        { title: "run_id", dataIndex: "run_id", width: 120, ellipsis: true, align: "center" },
      ]}
      pagination={pagination}
      scroll={{ y: 420, x: 900 }}
      noDataElement={<Empty description="暂无数据" />}
      border={false}
      tableLayout="fixed"
      className="logs-table"
      rowClassName={() => "log-row"}
    />
  );
}

export default function App() {
  const [range, setRange] = useDateRange();
  const [filters, setFilters] = useState({
    start: null,
    end: null,
    symbol: "",
    run_id: "",
    decision_type: "",
    event_type: "",
    keyword: "",
  });
  const [stats, setStats] = useState(null);
  const [eventTypes, setEventTypes] = useState([]);
  const [error, setError] = useState("");

  const refreshStats = async (nextFilters) => {
    if (!nextFilters.start || !nextFilters.end) return;
    try {
      const res = await fetchStats({ start: nextFilters.start, end: nextFilters.end });
      setStats(res);
      setError("");
    } catch (err) {
      setError(String(err));
    }
  };

  useEffect(() => {
    fetchEventEnum().then(setEventTypes).catch(() => {});
  }, []);

  useEffect(() => {
    const [s, e] = range;
    const next = {
      ...filters,
      start: s ? s.toISOString() : null,
      end: e ? e.toISOString() : null,
    };
    setFilters(next);
    refreshStats(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range]);

  return (
    <Layout style={{ minHeight: "100vh", padding: 24, background: "#f5f7fa" }}>
      <Layout.Header style={{ background: "transparent", padding: 0 }}>
        <h2>Coin Dash 日志面板</h2>
      </Layout.Header>
      <Layout.Content>
        <Space direction="vertical" style={{ width: "100%" }} size={16}>
          {error && <Alert type="error" content={error} />}
          <Card>
            <Form
              layout="inline"
              style={{ rowGap: 12 }}
              onSubmit={(vals) => {
                const [start, end] = range;
                const next = {
                  ...filters,
                  ...vals,
                  start: start?.toISOString(),
                  end: end?.toISOString(),
                };
                setFilters(next);
                refreshStats(next);
              }}
              initialValues={filters}
            >
              <Form.Item label="时间" required>
                <RangePicker
                  showTime
                  value={range}
                  onChange={(val) => setRange(val)}
                  style={{ width: 360 }}
                />
              </Form.Item>
              <Form.Item label="品种" field="symbol">
                <Input placeholder="可选，品种" allowClear />
              </Form.Item>
              <Form.Item label="run_id" field="run_id">
                <Input placeholder="可选，运行ID" allowClear />
              </Form.Item>
              <Form.Item label="决策类型" field="decision_type">
                <Input placeholder="open_long/open_short/hold" allowClear />
              </Form.Item>
              <Form.Item label="事件类型" field="event_type">
                <Input placeholder="从枚举选择/手填" allowClear />
              </Form.Item>
              <Form.Item label="关键词" field="keyword">
                <Input prefix={<IconSearch />} allowClear />
              </Form.Item>
              <Form.Item>
                <Space>
                  <Button type="primary" htmlType="submit">
                    查询
                  </Button>
                  <Button
                    onClick={() => {
                      const end = dayjs();
                      const start = end.subtract(24, "hour");
                      setRange([start, end]);
                      setFilters({
                        start: start.toISOString(),
                        end: end.toISOString(),
                        symbol: "",
                        run_id: "",
                        decision_type: "",
                        event_type: "",
                        keyword: "",
                      });
                      refreshStats({
                        start: start.toISOString(),
                        end: end.toISOString(),
                        symbol: "",
                        run_id: "",
                        decision_type: "",
                        event_type: "",
                        keyword: "",
                      });
                    }}
                  >
                    重置24h
                  </Button>
                </Space>
              </Form.Item>
            </Form>
          </Card>

          <Row gutter={16}>
            <Col span={6}>
              <Card>
                <Statistic title="调用总数" value={stats?.total ?? 0} />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic title="平均延迟(ms)" value={stats ? stats.avg_latency_ms.toFixed(1) : "-"} />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic title="Tokens" value={stats?.total_tokens ?? 0} />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic title="按品种数" value={stats?.by_symbol ? Object.keys(stats.by_symbol).length : 0} />
              </Card>
            </Col>
          </Row>

          <Card>
            <Tabs defaultActiveTab="decisions">
              <Tabs.TabPane key="decisions" title="决策日志">
                <DecisionTable filters={filters} />
              </Tabs.TabPane>
              <Tabs.TabPane key="events" title="系统事件">
                <EventList filters={filters} eventTypes={eventTypes} />
              </Tabs.TabPane>
              <Tabs.TabPane key="trades" title="交易 (待补)">
                <Alert type="info" content="可扩展调用 /api/trades 列表展示" />
              </Tabs.TabPane>
              <Tabs.TabPane key="signals" title="信号 (待补)">
                <Alert type="info" content="可扩展调用 /api/signals 列表展示" />
              </Tabs.TabPane>
            </Tabs>
          </Card>
        </Space>
      </Layout.Content>
    </Layout>
  );
}
