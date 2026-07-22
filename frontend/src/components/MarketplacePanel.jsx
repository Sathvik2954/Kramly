import { useState, useEffect } from "react";
import {
  fetchMarketplaceRecommendations,
  fetchResourceDetails,
  uploadResource,
  rateResource,
  supersedeResource,
  fetchResourceHistory
} from "../api/client";

export default function MarketplacePanel({ graphData }) {
  const [activeTab, setActiveTab] = useState("search");
  const [selectedSkill, setSelectedSkill] = useState("");
  const [recommendations, setRecommendations] = useState([]);
  const [recLoading, setRecLoading] = useState(false);
  const [recError, setRecError] = useState("");

  // Upload Form State
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadAuthor, setUploadAuthor] = useState("anonymous");
  const [uploadDesc, setUploadDesc] = useState("");
  const [uploadSkills, setUploadSkills] = useState([]);
  const [uploadContent, setUploadContent] = useState("");
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [uploadError, setUploadError] = useState("");

  // Reader Modal State
  const [readerResource, setReaderResource] = useState(null);
  const [readerContent, setReaderContent] = useState("");
  const [readerHistory, setReaderHistory] = useState([]);
  const [readerLoading, setReaderLoading] = useState(false);
  const [readerError, setReaderError] = useState("");

  // Rate rating inputs
  const [userRatings, setUserRatings] = useState({}); // { resourceId: ratingVal }

  useEffect(() => {
    if (graphData && graphData.nodes && graphData.nodes.length > 0 && !selectedSkill) {
      setSelectedSkill(graphData.nodes[0].id);
    }
  }, [graphData]);

  async function loadRecommendations(skillId) {
    if (!skillId) return;
    setRecLoading(true);
    setRecError("");
    try {
      const data = await fetchMarketplaceRecommendations(skillId);
      setRecommendations(data || []);
    } catch (e) {
      setRecError(e.message);
      setRecommendations([]);
    } finally {
      setRecLoading(false);
    }
  }

  async function handleSearch(e) {
    e.preventDefault();
    loadRecommendations(selectedSkill);
  }

  async function handleOpenReader(resourceId) {
    setReaderLoading(true);
    setReaderError("");
    setReaderResource(null);
    setReaderContent("");
    setReaderHistory([]);
    try {
      const data = await fetchResourceDetails(resourceId);
      setReaderResource(data.metadata || data);
      setReaderContent(data.content || "");

      try {
        const histData = await fetchResourceHistory(resourceId);
        setReaderHistory(histData.history || []);
      } catch (histErr) {
        console.warn("Failed to load superseded history", histErr);
      }
    } catch (e) {
      setReaderError(e.message);
    } finally {
      setReaderLoading(false);
    }
  }

  async function handleUpload(e) {
    e.preventDefault();
    if (!uploadTitle || !uploadContent) {
      setUploadError("Title and content are required.");
      return;
    }
    setUploadLoading(true);
    setUploadError("");
    setUploadResult(null);
    try {
      const result = await uploadResource({
        title: uploadTitle,
        author: uploadAuthor,
        description: uploadDesc,
        coveredSkills: uploadSkills,
        content: uploadContent
      });
      setUploadResult(result);
      setUploadTitle("");
      setUploadDesc("");
      setUploadContent("");
      setUploadSkills([]);
    } catch (e) {
      setUploadError(e.message);
    } finally {
      setUploadLoading(false);
    }
  }

  async function handleRate(resourceId, ratingValue) {
    try {
      await rateResource(resourceId, "student_user", ratingValue);
      setUserRatings(prev => ({ ...prev, [resourceId]: ratingValue }));
      if (selectedSkill) {
        loadRecommendations(selectedSkill);
      }
    } catch (e) {
      alert(`Failed to submit rating: ${e.message}`);
    }
  }

  const skillsList = graphData?.nodes || [];

  const tabButtonStyle = (isActive) => ({
    background: "none",
    border: "none",
    borderBottom: isActive ? "var(--border-w) solid var(--accent-primary)" : "var(--border-w) solid transparent",
    color: isActive ? "var(--text-primary)" : "var(--text-muted)",
    padding: "0.5rem 0.25rem",
    cursor: "pointer",
    fontWeight: 700,
    fontSize: "0.78rem",
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    fontFamily: "var(--font-mono)"
  });

  const fieldLabelStyle = { display: "block", fontSize: "0.72rem", marginBottom: "0.3rem", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 700 };
  const fieldInputStyle = { width: "100%" };

  return (
    <div>
      <div style={{ display: "flex", borderBottom: "var(--border-w) solid var(--border-color)", marginBottom: "1.25rem", gap: "1.5rem" }}>
        <button type="button" onClick={() => setActiveTab("search")} style={tabButtonStyle(activeTab === "search")}>
          Search &amp; Rate Resources
        </button>
        <button type="button" onClick={() => setActiveTab("upload")} style={tabButtonStyle(activeTab === "upload")}>
          Contribute Notes
        </button>
      </div>

      {activeTab === "search" && (
        <div>
          <form onSubmit={handleSearch} style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
            <select
              value={selectedSkill}
              onChange={(e) => setSelectedSkill(e.target.value)}
              style={{ flex: "1" }}
            >
              <option value="">-- Choose a Concept --</option>
              {skillsList.map((skill) => (
                <option key={skill.id} value={skill.id}>
                  {skill.name} ({skill.id})
                </option>
              ))}
            </select>
            <button type="submit" disabled={recLoading} className="btn">
              {recLoading ? "Searching..." : "Search"}
            </button>
          </form>

          {recError && <div className="error-badge" style={{ marginBottom: "1rem" }}>{recError}</div>}

          {recommendations.length === 0 && !recLoading && (
            <p style={{ color: "var(--text-muted)", fontSize: "0.8rem", textAlign: "center", padding: "1.5rem", fontFamily: "var(--font-mono)" }}>
              No learning resources have been uploaded for this concept yet.
            </p>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            {recommendations.map((rec) => {
              const rating = userRatings[rec.resource_id] || 0;
              return (
                <div
                  key={rec.resource_id}
                  style={{
                    padding: "1rem",
                    backgroundColor: "var(--bg-card)",
                    border: "var(--border-w) solid var(--border-color)",
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.5rem"
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div>
                      <h4 style={{ margin: "0", fontSize: "0.9rem", color: "var(--text-primary)" }}>
                        Resource ID: <code style={{ color: "var(--accent-primary)" }}>{rec.resource_id}</code>
                      </h4>
                      <p style={{ margin: "0.2rem 0 0 0", fontSize: "0.72rem", color: "var(--text-muted)" }}>
                        Reason: {rec.reason}
                      </p>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <span className="badge">
                        Match Score: {rec.score.toFixed(1)}
                      </span>
                    </div>
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "0.5rem", borderTop: "1px dashed var(--color-grey-mid)", paddingTop: "0.5rem" }}>
                    <button
                      type="button"
                      onClick={() => handleOpenReader(rec.resource_id)}
                      style={{ padding: "0.35rem 0.85rem", fontSize: "0.7rem" }}
                    >
                      Read Content &amp; Details
                    </button>

                    <div style={{ display: "flex", alignItems: "center", gap: "0.15rem" }}>
                      <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", marginRight: "0.35rem", fontFamily: "var(--font-mono)", textTransform: "uppercase" }}>Rate:</span>
                      {[1, 2, 3, 4, 5].map((val) => (
                        <span
                          key={val}
                          onClick={() => handleRate(rec.resource_id, val)}
                          style={{
                            cursor: "pointer",
                            fontSize: "1.1rem",
                            color: val <= rating ? "var(--accent-primary)" : "var(--color-grey-mid)"
                          }}
                        >
                          ★
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {activeTab === "upload" && (
        <form onSubmit={handleUpload} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div>
            <label style={fieldLabelStyle}>Resource Title *</label>
            <input
              type="text"
              required
              value={uploadTitle}
              onChange={(e) => setUploadTitle(e.target.value)}
              placeholder="e.g. Introduction to CSS Grid"
              style={fieldInputStyle}
            />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
            <div>
              <label style={fieldLabelStyle}>Author Name / ID *</label>
              <input
                type="text"
                required
                value={uploadAuthor}
                onChange={(e) => setUploadAuthor(e.target.value)}
                style={fieldInputStyle}
              />
            </div>
            <div>
              <label style={fieldLabelStyle}>Covered Skill Target</label>
              <select
                value={uploadSkills[0] || ""}
                onChange={(e) => setUploadSkills(e.target.value ? [e.target.value] : [])}
                style={fieldInputStyle}
              >
                <option value="">-- Choose Target Skill --</option>
                {skillsList.map((skill) => (
                  <option key={skill.id} value={skill.id}>
                    {skill.name} ({skill.id})
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label style={fieldLabelStyle}>Short Description</label>
            <input
              type="text"
              value={uploadDesc}
              onChange={(e) => setUploadDesc(e.target.value)}
              placeholder="e.g. Complete reference manual covering layout patterns."
              style={fieldInputStyle}
            />
          </div>

          <div>
            <label style={fieldLabelStyle}>Resource Content (Markdown or Text) *</label>
            <textarea
              required
              rows="6"
              value={uploadContent}
              onChange={(e) => setUploadContent(e.target.value)}
              placeholder="Write or paste your notes here..."
              style={{ ...fieldInputStyle, fontFamily: "var(--font-mono)", fontSize: "0.85rem" }}
            />
          </div>

          {uploadError && <div className="error-badge">{uploadError}</div>}

          {uploadResult && (
            <div style={{
              padding: "0.85rem 1rem",
              backgroundColor: "var(--accent-success-bg)",
              border: "var(--border-w) solid var(--border-color)",
              fontSize: "0.85rem"
            }}>
              <strong style={{ textTransform: "uppercase", fontSize: "0.75rem", letterSpacing: "0.04em" }}>Upload successful</strong>
              <p style={{ margin: "0.35rem 0 0 0", color: "var(--text-secondary)" }}>
                Resource ID: <code>{uploadResult.resource_id || uploadResult.id}</code>
              </p>
              <p style={{ margin: "0.25rem 0 0 0", color: "var(--text-secondary)" }}>
                Concept Extraction matched: <strong>{uploadResult.covered_skills?.join(", ") || "None"}</strong>
              </p>
            </div>
          )}

          <button type="submit" disabled={uploadLoading} className="btn" style={{ width: "100%" }}>
            {uploadLoading ? "Uploading & Analyzing..." : "Submit Notes"}
          </button>
        </form>
      )}

      {readerResource && (
        <div style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: "rgba(0,0,0,0.75)",
          zIndex: 1000,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          padding: "1rem"
        }}>
          <div style={{
            backgroundColor: "var(--bg-card)",
            border: "var(--border-thick) solid var(--border-color)",
            width: "100%",
            maxWidth: "650px",
            maxHeight: "85vh",
            display: "flex",
            flexDirection: "column",
            overflow: "hidden"
          }}>
            <div style={{
              padding: "1rem 1.5rem",
              borderBottom: "var(--border-w) solid var(--border-color)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center"
            }}>
              <div>
                <h3 style={{ margin: "0", fontSize: "1.05rem", color: "var(--text-primary)" }}>
                  {readerResource.title || `Resource: ${readerResource.id}`}
                </h3>
                <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                  By: {readerResource.author_id || readerResource.author} | Status:{" "}
                  <span style={{
                    marginLeft: "0.15rem",
                    fontWeight: 700,
                    color: readerResource.status === "outdated" ? "var(--accent-error)" : "var(--text-primary)"
                  }}>
                    {readerResource.status || "active"}
                  </span>
                </span>
              </div>
              <button
                type="button"
                onClick={() => setReaderResource(null)}
                style={{
                  background: "none",
                  border: "var(--border-w) solid var(--border-color)",
                  color: "var(--text-primary)",
                  fontSize: "1.1rem",
                  lineHeight: 1,
                  padding: "0.3rem 0.6rem",
                  cursor: "pointer"
                }}
              >
                &times;
              </button>
            </div>

            <div style={{ padding: "1.5rem", overflowY: "auto", flex: "1" }}>
              {readerResource.quality_score !== undefined && (
                <div style={{ marginBottom: "1rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", textTransform: "uppercase" }}>Quality Rating:</span>
                  <div style={{
                    flex: "1",
                    height: "8px",
                    backgroundColor: "var(--bg-muted)",
                    border: "1px solid var(--border-color)"
                  }}>
                    <div style={{
                      width: `${(readerResource.quality_score || 0) * 100}%`,
                      height: "100%",
                      backgroundColor: "var(--accent-primary)"
                    }}/>
                  </div>
                  <span style={{ fontSize: "0.78rem", fontWeight: "700", color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
                    {((readerResource.quality_score || 0) * 100).toFixed(0)}%
                  </span>
                </div>
              )}

              {readerHistory.length > 0 && (
                <div style={{
                  padding: "0.75rem",
                  backgroundColor: "var(--bg-muted)",
                  border: "1px solid var(--border-color)",
                  marginBottom: "1rem",
                  fontSize: "0.8rem"
                }}>
                  <strong style={{ display: "block", marginBottom: "0.35rem", textTransform: "uppercase", fontSize: "0.7rem", letterSpacing: "0.04em" }}>Version Provenance (Outdated History)</strong>
                  <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
                    {readerHistory.map(old => (
                      <li key={old.id} style={{ color: "var(--text-secondary)" }}>
                        {old.title || old.id} (<code>{old.id}</code>) — {old.status}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <pre style={{
                whiteSpace: "pre-wrap",
                fontFamily: "var(--font-mono)",
                fontSize: "0.85rem",
                backgroundColor: "var(--bg-muted)",
                padding: "1rem",
                border: "1px solid var(--border-color)",
                color: "var(--text-secondary)",
                margin: 0
              }}>
                {readerContent}
              </pre>
            </div>

            <div style={{
              padding: "1rem 1.5rem",
              borderTop: "var(--border-w) solid var(--border-color)",
              display: "flex",
              justifyContent: "flex-end"
            }}>
              <button type="button" onClick={() => setReaderResource(null)} className="btn" style={{ padding: "0.45rem 1.25rem" }}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
