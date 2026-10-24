import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, useAuth, date, experienceRange } from '../api.jsx';
import RichText from '../components/RichText.jsx';

export default function Jobs() {
  const { user } = useAuth();
  const companies = user.companies || [];
  const [rows, setRows] = useState([]);
  const multiCompany = companies.length > 1;
  const [fCompany, setFCompany] = useState('');   // company_code, '' = all
  const [fStatus, setFStatus] = useState('');     // OPEN | CLOSED | '' = all
  const [fPosted, setFPosted] = useState('');     // 7 | 30 | 90 days, '' = any time
  const [adding, setAdding] = useState(false);
  const [desc, setDesc] = useState('');        // the rich-text description in the create form
  const [editing, setEditing] = useState(null); // the opening being edited, as a working copy
  const [saving, setSaving] = useState(false);
  const [jd, setJd] = useState(null);          // the opening whose JD is being uploaded
  const [doomed, setDoomed] = useState(null);  // the opening being deleted, and its applicant count
  const [deleting, setDeleting] = useState(false);
  const [jdFile, setJdFile] = useState(null);
  const [jdText, setJdText] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');

  const load = () => api.get('/jobs').then(setRows).catch((e) => setError(e.message));

  // All rows are already in hand, so filtering is instant and needs no round-trip.
  const shown = useMemo(() => {
    const now = Date.now();
    return rows.filter((j) => {
      if (fCompany && j.company_code !== fCompany) return false;
      if (fStatus && j.status !== fStatus) return false;
      if (fPosted) {
        const age = (now - new Date(j.created_at).getTime()) / 86400000;
        if (age > Number(fPosted)) return false;
      }
      return true;
    });
  }, [rows, fCompany, fStatus, fPosted]);

  const filtersActive = fCompany || fStatus || fPosted;

  // Braces matter: passing `load` directly would hand React the promise it returns, and React
  // would try to call that promise as a cleanup function when you navigate away — "n is not a function".
  useEffect(() => { load(); }, []);

  const create = async (e) => {
    e.preventDefault();
    setError('');
    const body = Object.fromEntries(new FormData(e.target));
    try {
      await api.post('/jobs', { ...body, description: desc });
      setAdding(false);
      setDesc('');
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const [copiedId, setCopiedId] = useState(null);

  // The public, shareable link for one opening — paste into Naukri, LinkedIn, Indeed, etc.
  // Built from the careers page's own origin, which is where candidates land.
  const roleLink = (j) => `${window.location.origin}/careers?job=${j.id}`;

  const copyLink = async (j) => {
    const url = roleLink(j);
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      // Clipboard API is blocked on some setups; fall back to a manual select-copy.
      const el = document.createElement('textarea');
      el.value = url;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      el.remove();
    }
    setCopiedId(j.id);
    setTimeout(() => setCopiedId((c) => (c === j.id ? null : c)), 1800);
  };

  const askDelete = async (j) => {
    setError('');
    setMsg('');
    try {
      // The first call is a dry run: the server refuses if candidates are attached, and tells us how many.
      await api.del(`/jobs/${j.id}`);
      setMsg(`"${j.title}" deleted.`);
      load();
    } catch (err) {
      // 409 means "there are people attached" — show what will happen and let them decide.
      if (err.applicants) setDoomed({ job: j, applicants: err.applicants });
      else setError(err.message);
    }
  };

  const confirmDelete = async () => {
    setDeleting(true);
    try {
      const res = await api.del(`/jobs/${doomed.job.id}?force=true`);
      setMsg(
        `"${doomed.job.title}" deleted. ${res.applicants_detached} ` +
        `${res.applicants_detached === 1 ? 'candidate is' : 'candidates are'} still in the pipeline.`
      );
      setDoomed(null);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setDeleting(false);
    }
  };

  const openEdit = (j) => {
    setError('');
    setMsg('');
    setEditing({
      id: j.id,
      title: j.title,
      department: j.department || '',
      location: j.location || '',
      employment_type: j.employment_type || 'Full-time',
      min_experience: j.min_experience ?? 0,
      max_experience: j.max_experience ?? '',
      description: j.description || '',
      status: j.status,
    });
  };

  const saveEdit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      const { id, ...body } = editing;
      await api.patch(`/jobs/${id}`, body);
      setMsg(`"${editing.title}" updated.`);
      setEditing(null);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const setStatus = async (job, status) => {
    await api.patch(`/jobs/${job.id}`, { status });
    load();
  };

  const saveJd = async (e) => {
    e.preventDefault();
    setBusy(true); setError(''); setMsg('');
    try {
      const form = new FormData();
      if (jdFile) form.set('jd', jdFile);
      if (jdText.trim()) form.set('jd_text', jdText);
      const res = await api.upload(`/jobs/${jd.id}/jd`, form);
      setMsg(res.rescoring
        ? `Job description saved. Re-scoring ${res.rescoring} candidate${res.rescoring === 1 ? '' : 's'} already in the pipeline — refresh in a moment.`
        : 'Job description saved. Every resume for this role will now be scored against it.');
      setJd(null); setJdFile(null); setJdText('');
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Hiring</div>
          <h1>Openings</h1>
          <div className="sub">Open roles appear on the careers page immediately.</div>
        </div>
        <button onClick={() => setAdding(!adding)}>{adding ? 'Cancel' : 'Post an opening'}</button>
      </div>

      {msg && <div className="success" style={{ marginBottom: 16 }}>{msg}</div>}
      {error && !adding && !jd && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {!adding && rows.length > 0 && (
        <div className="row" style={{ marginBottom: 16, gap: 10, alignItems: 'flex-end' }}>
          {multiCompany && (
            <div>
              <label style={{ marginBottom: 4 }}>Company</label>
              <select value={fCompany} onChange={(e) => setFCompany(e.target.value)} style={{ width: 190 }}>
                <option value="">All companies</option>
                {companies.map((c) => <option key={c.id} value={c.code}>{c.code} — {c.name}</option>)}
              </select>
            </div>
          )}
          <div>
            <label style={{ marginBottom: 4 }}>Status</label>
            <select value={fStatus} onChange={(e) => setFStatus(e.target.value)} style={{ width: 150 }}>
              <option value="">Open &amp; closed</option>
              <option value="OPEN">Open only</option>
              <option value="CLOSED">Closed only</option>
            </select>
          </div>
          <div>
            <label style={{ marginBottom: 4 }}>Posted</label>
            <select value={fPosted} onChange={(e) => setFPosted(e.target.value)} style={{ width: 150 }}>
              <option value="">Any time</option>
              <option value="7">Last 7 days</option>
              <option value="30">Last 30 days</option>
              <option value="90">Last 90 days</option>
            </select>
          </div>
          {filtersActive && (
            <button className="ghost small" onClick={() => { setFCompany(''); setFStatus(''); setFPosted(''); }}>
              Clear
            </button>
          )}
          <div className="sub" style={{ marginLeft: 'auto', alignSelf: 'center' }}>
            {shown.length} of {rows.length}
          </div>
        </div>
      )}

      {doomed && (
        <div className="overlay" onClick={(e) => e.target === e.currentTarget && setDoomed(null)}>
          <div className="dialog" style={{ maxWidth: 480 }} role="dialog" aria-modal="true">
            <div className="dialog-head">
              <div>
                <div className="eyebrow">Delete opening</div>
                <h2>{doomed.job.title}</h2>
              </div>
              <button type="button" className="dialog-close" onClick={() => setDoomed(null)}>&times;</button>
            </div>
            <div className="dialog-body">
              <p style={{ marginTop: 0 }}>
                <strong>
                  {doomed.applicants} {doomed.applicants === 1 ? 'candidate has' : 'candidates have'} applied
                  for this opening.
                </strong>
              </p>
              <p>
                They stay in the pipeline and keep their resumes, scores and history. What they lose is the link
                to this opening — the role they applied for remains, as plain text.
              </p>
              <div className="note">
                The job description document is deleted with the opening. Resumes already scored keep their scores.
              </div>
            </div>
            <div className="dialog-foot">
              <button type="button" className="ghost" onClick={() => setDoomed(null)}>Keep it</button>
              <button type="button" className="danger" onClick={confirmDelete} disabled={deleting}>
                {deleting ? 'Deleting…' : 'Delete anyway'}
              </button>
            </div>
          </div>
        </div>
      )}

      {editing && (
        <div className="overlay" onClick={(e) => e.target === e.currentTarget && setEditing(null)}>
          <form className="dialog" style={{ maxWidth: 760 }} onSubmit={saveEdit}
                role="dialog" aria-modal="true">
            <div className="dialog-head">
              <div>
                <div className="eyebrow">Edit opening</div>
                <h2>{editing.title}</h2>
              </div>
              <button type="button" className="dialog-close" onClick={() => setEditing(null)}>&times;</button>
            </div>

            <div className="dialog-body">
              {error && <div className="error" style={{ marginBottom: 14 }}>{error}</div>}

              <div className="field">
                <label htmlFor="e_title">Role title</label>
                <input id="e_title" required value={editing.title}
                       onChange={(e) => setEditing({ ...editing, title: e.target.value })} />
              </div>

              <div className="field-row">
                <div className="field">
                  <label htmlFor="e_dept">Department</label>
                  <input id="e_dept" value={editing.department}
                         onChange={(e) => setEditing({ ...editing, department: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="e_loc">Location</label>
                  <input id="e_loc" value={editing.location}
                         onChange={(e) => setEditing({ ...editing, location: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="e_type">Employment type</label>
                  <select id="e_type" value={editing.employment_type}
                          onChange={(e) => setEditing({ ...editing, employment_type: e.target.value })}>
                    <option>Full-time</option>
                    <option>Contract</option>
                    <option>Internship</option>
                  </select>
                </div>
              </div>

              <div className="field-row">
                <div className="field">
                  <label htmlFor="e_min">Minimum experience (years)</label>
                  <input id="e_min" type="number" step="0.5" min="0" value={editing.min_experience}
                         onChange={(e) => setEditing({ ...editing, min_experience: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="e_max">Maximum experience (years)</label>
                  <input id="e_max" type="number" step="0.5" min="0" value={editing.max_experience}
                         placeholder="No limit"
                         onChange={(e) => setEditing({ ...editing, max_experience: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="e_status">Status</label>
                  <select id="e_status" value={editing.status}
                          onChange={(e) => setEditing({ ...editing, status: e.target.value })}>
                    <option value="OPEN">Open — shown on the careers page</option>
                    <option value="CLOSED">Closed — hidden from candidates</option>
                  </select>
                </div>
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label>What the role involves</label>
                <RichText value={editing.description} minHeight={260}
                          onChange={(html) => setEditing((j) => ({ ...j, description: html }))}
                          placeholder="Responsibilities, requirements, reporting line…" />
                <p className="sub" style={{ marginTop: 6 }}>
                  Changing this does not re-score resumes already in the pipeline. Upload or replace the JD
                  document to do that.
                </p>
              </div>
            </div>

            <div className="dialog-foot">
              <button type="button" className="ghost" onClick={() => setEditing(null)}>Cancel</button>
              <button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</button>
            </div>
          </form>
        </div>
      )}

      {jd && (
        <div className="overlay" onClick={(e) => e.target === e.currentTarget && setJd(null)}>
          <form className="dialog" style={{ maxWidth: 620 }} onSubmit={saveJd}
                role="dialog" aria-modal="true">
            <div className="dialog-head">
              <div>
                <div className="eyebrow">Job description</div>
                <h2>{jd.title}</h2>
              </div>
              <button type="button" className="dialog-close" onClick={() => setJd(null)} aria-label="Close">&times;</button>
            </div>

            <div className="dialog-body">
              {error && <div className="error" style={{ marginBottom: 14 }}>{error}</div>}
              <p style={{ marginTop: 0 }}>
                Every resume for this role is scored out of 10 against this description, and the candidate page shows
                which requirements the resume evidences and which it does not. Without a description, the score is
                based on the job title alone and means very little.
              </p>

              <div className="field">
                <label htmlFor="jd_file">Upload the job description — PDF, Word or text</label>
                <input id="jd_file" type="file" accept=".pdf,.doc,.docx,.txt"
                       onChange={(e) => setJdFile(e.target.files[0] || null)} />
              </div>

              <div className="field">
                <label htmlFor="jd_text">Or paste it in</label>
                <textarea id="jd_text" value={jdText} onChange={(e) => setJdText(e.target.value)}
                          style={{ minHeight: 160 }}
                          placeholder="Responsibilities, required qualifications, years of experience, software, codes…" />
              </div>

              {jd.has_jd && (
                <div className="note" style={{ marginBottom: 0 }}>
                  A description is already on file ({jd.jd_filename || 'pasted text'}). Saving a new one replaces it and
                  re-scores every candidate for this role, so the scores stay comparable.
                </div>
              )}
            </div>

            <div className="dialog-foot">
              <button type="button" className="ghost" onClick={() => setJd(null)}>Cancel</button>
              <button type="submit" disabled={busy || (!jdFile && !jdText.trim())}>
                {busy ? 'Saving…' : 'Save and score candidates'}
              </button>
            </div>
          </form>
        </div>
      )}

      {adding && (
        <form className="panel" onSubmit={create} style={{ marginBottom: 16 }}>
          <div className="panel-head"><h2>New opening</h2></div>
          <div className="panel-body">
            {error && <div className="error" style={{ marginBottom: 14 }}>{error}</div>}
            <div className="field-row">
              <div className="field">
                <label htmlFor="company_id">Company</label>
                <select id="company_id" name="company_id" required
                        defaultValue={companies.length === 1 ? companies[0].id : ''}>
                  <option value="" disabled>Select</option>
                  {companies.map((c) => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}
                </select>
              </div>
              <div className="field">
                <label htmlFor="title">Job title</label>
                <input id="title" name="title" required placeholder="Design Engineer — PEB" />
              </div>
              <div className="field">
                <label htmlFor="department">Department</label>
                <input id="department" name="department" />
              </div>
              <div className="field">
                <label htmlFor="location">Location</label>
                <input id="location" name="location" defaultValue="Chennai" />
              </div>
              <div className="field">
                <label htmlFor="min_experience">Minimum experience (years)</label>
                <input id="min_experience" name="min_experience" type="number" step="0.5" min="0" defaultValue="0" />
              </div>
              <div className="field">
                <label htmlFor="max_experience">Maximum experience (years)</label>
                <input id="max_experience" name="max_experience" type="number" step="0.5" min="0"
                       placeholder="No limit" />
              </div>
            </div>
            <div className="field">
              <label htmlFor="description">What the role involves</label>
              <RichText value={desc} onChange={setDesc}
                        placeholder="Responsibilities, what a good week looks like, the software and codes they will use, who they report to…" />
              <p className="sub" style={{ marginTop: 6 }}>
                This is what candidates read on the careers page. If you do not upload a separate JD document,
                resumes are scored against this.
              </p>
            </div>
            <button type="submit">Post opening</button>
          </div>
        </form>
      )}

      <div className="panel">
        {!rows.length ? (
          <div className="empty"><h3>No openings yet</h3><p>Post one and it goes live on the careers page.</p></div>
        ) : !shown.length ? (
          <div className="empty">
            <h3>No openings match</h3>
            <p>Nothing fits these filters.{' '}
              <button className="ghost small" onClick={() => { setFCompany(''); setFStatus(''); setFPosted(''); }}>
                Clear filters
              </button>
            </p>
          </div>
        ) : (
          <table>
            <thead>
              <tr><th>Role</th><th>Location</th><th>Min. experience</th><th>Job description</th><th>Applicants</th><th>Status</th><th>Posted</th><th></th></tr>
            </thead>
            <tbody>
              {shown.map((j) => (
                <tr key={j.id} style={{ cursor: 'default' }}>
                  <td className="co" style={{ borderLeftColor: j.colour }}>
                    <div className="name">{j.title}</div>
                    <div className="ref">{j.company_code}{j.department ? ` · ${j.department}` : ''}</div>
                  </td>
                  <td>{j.location || '—'}</td>
                  <td>{experienceRange(j.min_experience, j.max_experience)}</td>
                  <td>
                    {j.has_jd
                      ? <span className="chip JOINED">On file</span>
                      : <span className="chip ON_HOLD">Not uploaded</span>}
                  </td>
                  <td>
                    {j.applicant_count > 0 ? (
                      <Link to={`/pipeline?job=${j.id}&jobtitle=${encodeURIComponent(j.title)}`}
                            className="applicant-link" title="View these applicants">
                        <strong>{j.applicant_count}</strong>
                      </Link>
                    ) : (
                      <strong style={{ color: 'var(--muted)' }}>0</strong>
                    )}
                  </td>
                  <td><span className={`chip ${j.status === 'OPEN' ? 'JOINED' : j.status === 'CLOSED' ? 'REJECTED' : 'ON_HOLD'}`}>{j.status}</span></td>
                  <td className="sub">{date(j.created_at)}</td>
                  <td>
                    <div className="row">
                      <button className="ghost small" onClick={() => openEdit(j)}>Edit</button>
                      {j.status === 'OPEN' && (
                        <button className="ghost small" onClick={() => copyLink(j)}
                                title="Copy the public apply link to share on job portals">
                          {copiedId === j.id ? '✓ Copied' : 'Copy link'}
                        </button>
                      )}
                      <button className="ghost small" onClick={() => { setJd(j); setJdText(''); setJdFile(null); setMsg(''); }}>
                        {j.has_jd ? 'Replace JD' : 'Upload JD'}
                      </button>
                      {user.role === 'SUPER_ADMIN' && (
                        <button className="ghost small" onClick={() => askDelete(j)}
                                style={{ color: 'var(--red)', borderColor: 'var(--line)' }}>
                          Delete
                        </button>
                      )}
                      {j.status === 'OPEN'
                        ? <button className="ghost small" onClick={() => setStatus(j, 'CLOSED')}>Close</button>
                        : <button className="ghost small" onClick={() => setStatus(j, 'OPEN')}>Reopen</button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
