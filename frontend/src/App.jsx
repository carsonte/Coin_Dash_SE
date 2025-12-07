import React, { useState } from "react";
import { Layout, Menu } from "antd";
import Dashboard from "./pages/Dashboard";
import LogsPage from "./pages/LogsPage";

const { Header, Content, Sider } = Layout;

export default function App() {
  const [activeMenuKey, setActiveMenuKey] = useState("dashboard");
  const [logsPrefill, setLogsPrefill] = useState(null);

  const handleNavigateToLogs = (symbol, runId) => {
    setLogsPrefill({ symbol, run_id: runId });
    setActiveMenuKey("logs");
  };

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider width={220} style={{ background: "#fff" }}>
        <div style={{ padding: "16px 12px", fontWeight: 600, fontSize: 16 }}>Console</div>
        <Menu
          mode="inline"
          selectedKeys={[activeMenuKey]}
          onClick={({ key }) => setActiveMenuKey(key)}
          items={[
            { key: "dashboard", label: "Dashboard" },
            { key: "logs", label: "Logs" },
          ]}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: "#fff",
            padding: "0 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderBottom: "1px solid #f0f0f0",
          }}
        >
          <div style={{ fontSize: 20, fontWeight: 600 }}>Coin Dash SE Monitor</div>
          <div style={{ color: "#666", fontSize: 14 }}>
            {activeMenuKey === "logs" ? "AI 决策 & 多模型委员会" : "仪表盘"}
          </div>
        </Header>
        <Content style={{ padding: 16, background: "#f5f7fa" }}>
          {activeMenuKey === "dashboard" && <Dashboard onNavigateToLogs={handleNavigateToLogs} />}
          {activeMenuKey === "logs" && <LogsPage prefill={logsPrefill} />}
        </Content>
      </Layout>
    </Layout>
  );
}
