import React, { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Tooltip,
  message,
  Spin,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import {
  fetchStats,
  fetchDecisions,
  fetchDecisionDetail,
  fetchEvents,
  fetchTrades,
  fetchSignals,
} from "../api";
import "../table.css";

const { RangePicker } = DatePicker;
const modelOptions = [
  { label: "deepseek", value: "deepseek" },
  { label: "gpt-4o-mini", value: "gpt-4o-mini" },
  { label: "qwen", value: "qwen" },
  { label: "committee", value: "committee" },
];

const decisionTypeOptions = [
  { label: "开多", value: "open_long" },
  { label: "开空", value: "open_short" },
  { label: "平仓", value: "close" },
  { label: "观望", value: "hold" },
  { label: "复评", value: "review" },
];

function useDateRange(defaultHours = 24) {
  const end = dayjs();
  const start = end.subtract(defaultHours, "hour");
  return [start, end];
}

function LogsFilterForm({ value, onChange, symbolOptions, runIdOptions }) {
  const [form] = Form.useForm();

  useEffect(() => {
    form.setFieldsValue({
      ...value,
      range: value.start && value.end ? [dayjs(value.start), dayjs(value.end)] : undefined,
      run_id: value.run_id ? [value.run_id] : [],
    });
  }, [value, form]);

  const handleFinish = (vals) => {
    const [s, e] = vals.range || [];
    const runIdVal = Array.isArray(vals.run_id) ? vals.run_id[0] || "" : vals.run_id || "";
    onChange({
      ...value,
      start: s ? s.toISOString() : null,
      end: e ? e.toISOString() : null,
      symbols: vals.symbols || [],
      run_id: runIdVal,
      decision_type: vals.decision_type || "",
      model_name: vals.model_name || "",
      committee_id: vals.committee_id || "",
      keyword: vals.keyword || "",
    });
  };

  return (
    <Card>
      <Form
        form={form}
        layout="inline"
        style={{ rowGap: 12, width: "100%" }}
        onFinish={handleFinish}
      >
        <Form.Item
          label="时间范围"
          name="range"
          rules={[{ required: true, message: "请选择时间范围" }]}
        >
          <RangePicker showTime style={{ width: 360 }} />
        </Form.Item>
        <Form.Item label="symbol" name="symbols">
          <Select
            mode="tags"
            placeholder="多选/自定义"
            style={{ width: 180 }}
            options={(symbolOptions || []).map((s) => ({ label: s, value: s }))}
            allowClear
          />
        </Form.Item>
        <Form.Item label="run_id" name="run_id">
          <Select
            mode="tags"
            maxTagCount={1}
            placeholder="可选"
            style={{ width: 180 }}
            options={(runIdOptions || []).map((s) => ({ label: s, value: s }))}
            allowClear
          />
        </Form.Item>
        <Form.Item label="决策类型" name="decision_type">
          <Select
            allowClear
            placeholder="选择"
            style={{ width: 160 }}
            options={decisionTypeOptions}
          />
        </Form.Item>
        <Form.Item label="model_name" name="model_name">
          <Select allowClear placeholder="模型" style={{ width: 160 }} options={modelOptions} />
        </Form.Item>
        <Form.Item label="committee_id" name="committee_id">
          <Input placeholder="精确投票 ID" style={{ width: 180 }} />
        </Form.Item>
        <Form.Item label="关键词" name="keyword">
          <Input prefix={<SearchOutlined />} allowClear style={{ width: 180 }} />
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
                form.setFieldsValue({
                  range: [start, end],
                  symbols: [],
                  run_id: [],
                  decision_type: undefined,
                  model_name: undefined,
                  committee_id: "",
                  keyword: "",
                });
                handleFinish({
                  range: [start, end],
                  symbols: [],
                  run_id: "",
                  decision_type: "",
                  model_name: "",
                  committee_id: "",
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
  );
}

function StatsCards({ decisions }) {
  const total = decisions.total || 0;
  const getDecision = (d) =>
    (d.decision_code || d.result?.decision || d.decision_type || "").toString().toLowerCase();
  const finalOpen = (decisions.items || []).filter((d) => d.is_final && getDecision(d).startsWith("open")).length;
  const holdCount = (decisions.items || []).filter((d) => getDecision(d) === "hold").length;

  const data = [
    { title: "决策总数", value: total },
    { title: "最终开仓数", value: finalOpen },
    { title: "观望数", value: holdCount },
  ];
  return (
    <Row gutter={16}>
      {data.map((item) => (
        <Col span={8} key={item.title}>
          <Card>
            <Statistic title={item.title} value={item.value} />
          </Card>
        </Col>
      ))}
    </Row>
  );
}

function DecisionDrawer({ open, onClose, detail, committeeRecords, loadingCommittee }) {
  const glm = detail?.result?.glm_snapshot || detail?.result?.glm_filter_result;
  const splitReason = (text) => {
    if (!text) return [];
    return text
      .split(/[\n；。;•-]/)
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 5);
  };

  const renderModelCard = (record) => {
    const res = record?.result || {};
    const bullets = splitReason(res.reason || res.summary || "");
    return (
      <Card size="small" title={record.model_name || "-"} style={{ marginBottom: 12 }}>
        <Space direction="vertical" style={{ width: "100%" }}>
          <div>方向：{res.direction || res.decision || record.decision_type || "-"}</div>
          <div>
            入场/止损/止盈：{res.entry_price ?? "-"} / {res.stop_loss ?? "-"} / {res.take_profit ?? "-"}
          </div>
          <div>RR：{res.rr ?? "-"}</div>
          <div>置信度：{record.confidence ?? "-"}</div>
          {bullets.length > 0 && (
            <List
              size="small"
              dataSource={bullets}
              renderItem={(b, idx) => <List.Item key={idx}>• {b}</List.Item>}
            />
          )}
        </Space>
      </Card>
    );
  };

  const committeeCard = committeeRecords.find((r) => r.is_final);
  const modelCards = committeeRecords.filter((r) => !r.is_final);

  return (
    <Drawer title="决策详情" width={900} open={open} onClose={onClose} destroyOnClose>
      {detail ? (
        <Space direction="vertical" style={{ width: "100%" }} size={16}>
          <Card title="最终决策">
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="symbol">{detail.symbol}</Descriptions.Item>
              <Descriptions.Item label="决策类型">{detail.decision_type}</Descriptions.Item>
              <Descriptions.Item label="run_id">{detail.run_id}</Descriptions.Item>
              <Descriptions.Item label="committee_id">{detail.committee_id || "-"}</Descriptions.Item>
              <Descriptions.Item label="模型">{detail.model_name}</Descriptions.Item>
              <Descriptions.Item label="置信度">{detail.confidence ?? "-"}</Descriptions.Item>
              <Descriptions.Item label="entry/stop/tp">
                {(detail.result?.entry_price ?? "-")}/{detail.result?.stop_loss ?? "-"}/{detail.result?.take_profit ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="RR">{detail.result?.rr ?? "-"}</Descriptions.Item>
              <Descriptions.Item label="评分/权重">
                {(detail.weight ?? "-")} / {detail.result?.score ?? "-"}
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <Card title="模型投票">
            <Row gutter={12}>
              {loadingCommittee && (
                <Col span={24}>
                  <Spin />
                </Col>
              )}
              {!loadingCommittee && modelCards.length === 0 && <Empty description="暂无投票数据" />}
              {!loadingCommittee &&
                modelCards.map((rec) => (
                  <Col span={8} key={rec.id || rec.model_name}>
                    {renderModelCard(rec)}
                  </Col>
                ))}
            </Row>
          </Card>

          {glm && (
            <Collapse defaultActiveKey={["glm"]}>
              <Collapse.Panel header="GLM 预过滤 / 市场状态" key="glm">
                <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(glm, null, 2)}</pre>
              </Collapse.Panel>
            </Collapse>
          )}

          <Collapse>
            <Collapse.Panel header="Payload" key="payload">
              <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(detail.payload, null, 2)}</pre>
            </Collapse.Panel>
            <Collapse.Panel header="Result" key="result">
              <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(detail.result, null, 2)}</pre>
            </Collapse.Panel>
          </Collapse>
        </Space>
      ) : (
        <Spin />
      )}
    </Drawer>
  );
}

function DecisionsTab({ filters, onDataChange }) {
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState({ current: 1, pageSize: 20 });
  const [detail, setDetail] = useState(null);
  const [committeeRecords, setCommitteeRecords] = useState([]);
  const [loadingCommittee, setLoadingCommittee] = useState(false);
  const [detailCache, setDetailCache] = useState({});

  const decisionLabel = (code) => {
    const map = {
      open_long: "开多",
      open_short: "开空",
      close: "平仓",
      hold: "观望",
      review: "复评",
      decision: "决策",
    };
    if (!code) return "-";
    const key = code.toString().toLowerCase();
    return map[key] || key;
  };

  const pickDecisionCode = (record, detailsMap) => {
    const detailItem = detailsMap?.[record.id];
    return (
      (detailItem?.result?.decision || detailItem?.decision_type || record.result?.decision || record.decision_type || "")
        .toString()
        .toLowerCase()
    );
  };

  const load = async (pg = page, nextFilters = filters) => {
    if (!nextFilters.start || !nextFilters.end) return;
    setLoading(true);
    try {
      const res = await fetchDecisions({
        start: nextFilters.start,
        end: nextFilters.end,
        symbol: nextFilters.symbols?.[0] || nextFilters.symbol || undefined,
        run_id: nextFilters.run_id || undefined,
        decision_type: nextFilters.decision_type || undefined,
        model_name: nextFilters.model_name || undefined,
        committee_id: nextFilters.committee_id || undefined,
        keyword: nextFilters.keyword || undefined,
        limit: pg.pageSize,
        offset: (pg.current - 1) * pg.pageSize,
      });
      const baseItems = res.items || [];
      // 拉取详情以获得真实的 decision 字段
      const cached = { ...detailCache };
      const details = await Promise.all(
        baseItems.map(async (item) => {
          if (cached[item.id]) return cached[item.id];
          try {
            const d = await fetchDecisionDetail(item.id);
            cached[item.id] = d;
            return d;
          } catch (e) {
            return null;
          }
        })
      );
      const enriched = baseItems.map((item, idx) => {
        const detailItem = details[idx] || cached[item.id];
        const code = pickDecisionCode(item, cached);
        return { ...item, decision_code: code, _detail: detailItem };
      });
      setDetailCache(cached);
      setData({ items: enriched, total: res.total || 0 });
      onDataChange?.({ items: enriched, total: res.total || 0 });
    } catch (err) {
      message.error(`决策列表获取失败: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setPage({ current: 1, pageSize: page.pageSize });
    load({ current: 1, pageSize: page.pageSize }, filters);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  const loadCommittee = async (committeeId, centerTime) => {
    if (!committeeId) {
      setCommitteeRecords([]);
      return;
    }
    setLoadingCommittee(true);
    try {
      const start = centerTime ? dayjs(centerTime).subtract(1, "day").toISOString() : filters.start;
      const end = centerTime ? dayjs(centerTime).add(1, "day").toISOString() : filters.end;
      const res = await fetchDecisions({
        start,
        end,
        committee_id: committeeId,
        limit: 20,
        offset: 0,
      });
      setCommitteeRecords(res.items || []);
    } catch (err) {
      message.error(`委员会记录获取失败: ${err}`);
    } finally {
      setLoadingCommittee(false);
    }
  };

  const columns = useMemo(
    () => [
      { title: "时间", dataIndex: "created_at", width: 160, ellipsis: true, align: "center" },
      { title: "symbol", dataIndex: "symbol", width: 100, ellipsis: true, align: "center" },
      {
        title: "决策类型",
        dataIndex: "decision_type",
        width: 120,
        ellipsis: true,
        align: "center",
        render: (_, record) => decisionLabel(record.decision_code || record.decision_type),
      },
      {
        title: "model_name",
        dataIndex: "model_name",
        width: 140,
        align: "center",
        render: (v) => <Tag>{v || "-"}</Tag>,
      },
      { title: "committee_id", dataIndex: "committee_id", width: 160, ellipsis: true },
      { title: "weight", dataIndex: "weight", width: 80, align: "center" },
      {
        title: "is_final",
        dataIndex: "is_final",
        width: 100,
        align: "center",
        render: (v) => (v ? <Tag color="green">最终决策</Tag> : <Tag>非最终</Tag>),
      },
      { title: "置信度", dataIndex: "confidence", width: 100, align: "center" },
      { title: "Tokens", dataIndex: "tokens_used", width: 100, align: "center" },
      { title: "延迟(ms)", dataIndex: "latency_ms", width: 100, align: "center" },
      {
        title: "理由摘要",
        dataIndex: "reason_snippet",
        width: 240,
        ellipsis: true,
        render: (val) => (
          <Tooltip title={val || ""} placement="top">
            <span className="nowrap-cell">{val || ""}</span>
          </Tooltip>
        ),
      },
      { title: "run_id", dataIndex: "run_id", width: 140, ellipsis: true, align: "center" },
      {
        title: "操作",
        width: 100,
        align: "center",
        render: (_, record) => (
          <Button
            type="link"
            onClick={async () => {
              try {
                const res = await fetchDecisionDetail(record.id);
                setDetail(res);
                loadCommittee(res.committee_id, res.created_at);
              } catch (err) {
                message.error(`加载详情失败: ${err}`);
              }
            }}
          >
            查看详情
          </Button>
        ),
      },
    ],
    []
  );

  const pagination = {
    current: page.current,
    pageSize: page.pageSize,
    total: data.total,
    showSizeChanger: false,
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
        dataSource={data.items}
        columns={columns}
        pagination={pagination}
        rowKey="id"
        scroll={{ x: 1400 }}
        locale={{ emptyText: <Empty description="暂无数据" /> }}
        tableLayout="fixed"
        className="logs-table"
        rowClassName={() => "log-row"}
      />
      <DecisionDrawer
        open={!!detail}
        onClose={() => setDetail(null)}
        detail={detail}
        committeeRecords={committeeRecords}
        loadingCommittee={loadingCommittee}
      />
    </>
  );
}

function TradesTab({ filters }) {
  const [data, setData] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState({ current: 1, pageSize: 20 });

  const load = async (pg = page) => {
    if (!filters.start || !filters.end) return;
    setLoading(true);
    try {
      const res = await fetchTrades({
        start: filters.start,
        end: filters.end,
        symbol: filters.symbols?.[0],
        run_id: filters.run_id || undefined,
        limit: pg.pageSize,
        offset: (pg.current - 1) * pg.pageSize,
      });
      setData(res.items || []);
      setTotal(res.total || 0);
    } catch (err) {
      message.error(`交易列表获取失败: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setPage({ current: 1, pageSize: page.pageSize });
    load({ current: 1, pageSize: page.pageSize });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  const columns = [
    { title: "时间", dataIndex: "opened_at", width: 160, ellipsis: true },
    { title: "symbol", dataIndex: "symbol", width: 100 },
    { title: "方向", dataIndex: "side", width: 80 },
    { title: "开仓价", dataIndex: "entry_price", width: 100 },
    { title: "止损", dataIndex: "stop_loss", width: 100 },
    { title: "止盈", dataIndex: "take_profit", width: 100 },
    { title: "RR", dataIndex: "rr", width: 80 },
    { title: "状态", dataIndex: "status", width: 100 },
    { title: "run_id", dataIndex: "run_id", width: 140, ellipsis: true },
  ];

  const pagination = {
    current: page.current,
    pageSize: page.pageSize,
    total,
    showSizeChanger: false,
    onChange: (current, pageSize) => {
      const newPg = { current, pageSize };
      setPage(newPg);
      load(newPg);
    },
  };

  return (
    <Table
      loading={loading}
      dataSource={data}
      rowKey="id"
      columns={columns}
      pagination={pagination}
      scroll={{ x: 900 }}
      locale={{ emptyText: <Empty description="暂无数据" /> }}
      tableLayout="fixed"
      className="logs-table"
      rowClassName={() => "log-row"}
    />
  );
}

function SignalsTab({ filters }) {
  const [data, setData] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState({ current: 1, pageSize: 20 });

  const load = async (pg = page) => {
    if (!filters.start || !filters.end) return;
    setLoading(true);
    try {
      const res = await fetchSignals({
        start: filters.start,
        end: filters.end,
        symbol: filters.symbols?.[0],
        run_id: filters.run_id || undefined,
        limit: pg.pageSize,
        offset: (pg.current - 1) * pg.pageSize,
      });
      setData(res.items || []);
      setTotal(res.total || 0);
    } catch (err) {
      message.error(`信号列表获取失败: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setPage({ current: 1, pageSize: page.pageSize });
    load({ current: 1, pageSize: page.pageSize });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  const columns = [
    { title: "时间", dataIndex: "created_at", width: 160, ellipsis: true },
    { title: "symbol", dataIndex: "symbol", width: 100 },
    { title: "方向", dataIndex: "direction", width: 80 },
    { title: "entry", dataIndex: "entry_price", width: 100 },
    { title: "止损", dataIndex: "stop_loss", width: 100 },
    { title: "止盈", dataIndex: "take_profit", width: 100 },
    { title: "RR", dataIndex: "risk_reward", width: 80 },
    { title: "状态", dataIndex: "status", width: 100 },
    { title: "run_id", dataIndex: "run_id", width: 140, ellipsis: true },
  ];

  const pagination = {
    current: page.current,
    pageSize: page.pageSize,
    total,
    showSizeChanger: false,
    onChange: (current, pageSize) => {
      const newPg = { current, pageSize };
      setPage(newPg);
      load(newPg);
    },
  };

  return (
    <Table
      loading={loading}
      dataSource={data}
      rowKey="id"
      columns={columns}
      pagination={pagination}
      scroll={{ x: 900 }}
      locale={{ emptyText: <Empty description="暂无数据" /> }}
      tableLayout="fixed"
      className="logs-table"
      rowClassName={() => "log-row"}
    />
  );
}

function EventsTab({ filters }) {
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
        run_id: filters.run_id || undefined,
        keyword: filters.keyword || undefined,
        limit: pg.pageSize,
        offset: (pg.current - 1) * pg.pageSize,
      });
      setData(res.items || []);
      setTotal(res.total || 0);
    } catch (err) {
      message.error(`系统事件获取失败: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setPage({ current: 1, pageSize: page.pageSize });
    load({ current: 1, pageSize: page.pageSize });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  const columns = [
    { title: "时间", dataIndex: "created_at", width: 160, ellipsis: true, align: "center" },
    { title: "事件", dataIndex: "event_type", width: 160, ellipsis: true, align: "center" },
    {
      title: "级别",
      dataIndex: "severity",
      width: 100,
      align: "center",
      render: (v) => <Tag color={v === "ERROR" ? "red" : v === "WARNING" ? "gold" : "blue"}>{v}</Tag>,
    },
    {
      title: "描述",
      dataIndex: "description",
      width: 280,
      ellipsis: true,
      render: (v) => (
        <Tooltip title={v || ""} placement="top">
          <span className="nowrap-cell">{v || ""}</span>
        </Tooltip>
      ),
    },
    { title: "run_id", dataIndex: "run_id", width: 140, ellipsis: true },
  ];

  const pagination = {
    current: page.current,
    pageSize: page.pageSize,
    total,
    showSizeChanger: false,
    onChange: (current, pageSize) => {
      const newPg = { current, pageSize };
      setPage(newPg);
      load(newPg);
    },
  };

  return (
    <Table
      loading={loading}
      dataSource={data}
      rowKey="id"
      columns={columns}
      pagination={pagination}
      scroll={{ x: 800 }}
      locale={{ emptyText: <Empty description="暂无数据" /> }}
      tableLayout="fixed"
      className="logs-table"
      rowClassName={() => "log-row"}
    />
  );
}

export default function LogsPage({ prefill }) {
  const [startDefault, endDefault] = useDateRange();
  const [filters, setFilters] = useState({
    start: startDefault.toISOString(),
    end: endDefault.toISOString(),
    symbols: [],
    run_id: "",
    decision_type: "",
    model_name: "",
    committee_id: "",
    keyword: "",
  });
  const [stats, setStats] = useState(null);
  const [activeTab, setActiveTab] = useState("decisions");
  const [symbolOptions, setSymbolOptions] = useState([]);
  const [runIdOptions, setRunIdOptions] = useState([]);
  const [error, setError] = useState("");
  const [decisionSummary, setDecisionSummary] = useState({ items: [], total: 0 });

  useEffect(() => {
    if (prefill) {
      const next = {
        ...filters,
        symbols: prefill.symbol ? [prefill.symbol] : filters.symbols,
        run_id: prefill.run_id || "",
      };
      setFilters(next);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill]);

  const refreshStats = async (nextFilters) => {
    if (!nextFilters.start || !nextFilters.end) return;
    try {
      const res = await fetchStats({ start: nextFilters.start, end: nextFilters.end });
      setStats(res);
      setSymbolOptions(res?.by_symbol ? Object.keys(res.by_symbol) : []);
      setRunIdOptions(res?.by_run_id ? Object.keys(res.by_run_id) : []);
      setError("");
    } catch (err) {
      setError(String(err));
    }
  };

  useEffect(() => {
    refreshStats(filters);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.start, filters.end]);

  return (
    <Space direction="vertical" style={{ width: "100%" }} size={16}>
      {error && <Alert type="error" message={error} showIcon />}
      <LogsFilterForm value={filters} onChange={setFilters} symbolOptions={symbolOptions} runIdOptions={runIdOptions} />
      <StatsCards decisions={decisionSummary.total ? decisionSummary : { items: [], total: stats?.total ?? 0 }} />
      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab}>
          <Tabs.TabPane key="decisions" tab="AI 决策">
            <DecisionsTab filters={filters} onDataChange={setDecisionSummary} />
          </Tabs.TabPane>
          <Tabs.TabPane key="trades" tab="交易">
            <TradesTab filters={filters} />
          </Tabs.TabPane>
          <Tabs.TabPane key="signals" tab="信号">
            <SignalsTab filters={filters} />
          </Tabs.TabPane>
          <Tabs.TabPane key="events" tab="系统事件">
            <EventsTab filters={filters} />
          </Tabs.TabPane>
        </Tabs>
      </Card>
    </Space>
  );
}
