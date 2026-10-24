import { useEffect, useState } from 'react';
import { api, experienceRange } from '../api.jsx';
import { GroupLogo, CompanyLogo } from '../components/Logo.jsx';

export default function Careers() {
  const [openings, setOpenings] = useState([]);
  const [job, setJob] = useState(null);
  const [file, setFile] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);

  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    api.get('/public/openings').then(setOpenings).catch((e) => setError(e.message));
  }, []);

  // A shared link — /careers?job=<id> — opens straight to that role's apply form. Used when a
  // posting on a job portal links back here. If the role has since closed, say so rather than
  // silently dropping the visitor on the full list.
  useEffect(() => {
    if (!openings.length) return;
    const wanted = new URLSearchParams(window.location.search).get('job');
    if (!wanted) return;
    const match = openings.find((o) => String(o.id) === String(wanted));
    if (match) openJob(match);
    else setNotFound(true);
  }, [openings]);

  // Escape closes the form, the way any dialog should.
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && closeJob();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const openJob = (o) => {
    setJob(o);
    setError('');
    setFile(null);
    document.body.style.overflow = 'hidden'; // stop the page scrolling behind the dialog
  };

  const closeJob = () => {
    setJob(null);
    setError('');
    setFile(null);
    document.body.style.overflow = '';
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!job) return setError('Choose the role you are applying for.');
    setBusy(true);
    setError('');

    const form = new FormData(e.target);
    form.set('company_id', job.company_id);
    form.set('job_id', job.id);
    form.set('position_applied', job.title);
    if (file) form.set('resume', file);

    try {
      const res = await api.upload('/public/apply', form);
      setDone(res.ref_code);
      closeJob();
      window.scrollTo(0, 0);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (done)
    return (
      <div className="public">
        <div className="public-head">
          <GroupLogo />
          <div className="sub">Careers</div>
        </div>
        <div className="success" style={{ padding: 20 }}>
          <h2 style={{ marginBottom: 8 }}>Application received</h2>
          <p style={{ margin: 0 }}>
            Your reference number is <strong style={{ fontFamily: 'var(--f-mono)' }}>{done}</strong>. Keep it — quote it
            in any follow-up. Our HR team reviews every application and will contact you if your profile matches.
          </p>
        </div>
        <p style={{ marginTop: 20 }}>
          <button className="ghost" onClick={() => setDone(null)}>
            Apply for another role
          </button>
        </p>
      </div>
    );

  const byCompany = openings.reduce((acc, o) => {
    (acc[o.company_name] ||= []).push(o);
    return acc;
  }, {});

  return (
    <div className="public">
      <div className="public-head">
        <GroupLogo />
        <div className="sub">Careers · Chennai</div>
      </div>

      <p style={{ maxWidth: 620, marginBottom: 28 }}>
        Steel trading and processing, pre-engineered buildings, roofing systems and software — four companies, one
        group. Pick a role, tell us how to reach you, and attach your resume.
      </p>

      <h2 style={{ marginBottom: 12 }}>Open roles</h2>
      {notFound && !job && (
        <div className="note" style={{ marginBottom: 20 }}>
          That role is no longer open. Browse the current openings below.
        </div>
      )}

      {!openings.length && <div className="empty">No roles are open right now. Check back soon.</div>}

      {Object.entries(byCompany).map(([company, list]) => (
        <div key={company} style={{ marginBottom: 26 }}>
          <div style={{ marginBottom: 10, paddingBottom: 8, borderBottom: '1px solid var(--line)' }}>
            <CompanyLogo code={list[0].company_code} name={company} />
          </div>
          {list.map((o) => (
            <div key={o.id}
                 className="opening"
                 style={{ borderLeftColor: o.colour }}
                 onClick={() => openJob(o)}
                 role="button" tabIndex={0}
                 onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && openJob(o)}>
              <div>
                <div className="name">{o.title}</div>
                <div className="sub">
                  {[o.department, o.location, experienceRange(o.min_experience, o.max_experience)]
                    .filter(Boolean).join(' · ')}
                </div>
              </div>
              <span className="chip">Apply</span>
            </div>
          ))}
        </div>
      ))}

      {job && (
        <div className="overlay" onClick={(e) => e.target === e.currentTarget && closeJob()}>
          <form className="dialog" onSubmit={submit} role="dialog" aria-modal="true"
                aria-label={`Apply for ${job.title}`}>
            <div className="dialog-head">
              <div>
                <CompanyLogo code={job.company_code} name={job.company_name} className="co-logo-sm" />
                <h2 style={{ marginTop: 8 }}>{job.title}</h2>
                <div className="sub">
                  {[job.department, job.location, experienceRange(job.min_experience, job.max_experience)]
                    .filter(Boolean).join(' · ')}
                </div>
              </div>
              <button type="button" className="dialog-close" onClick={closeJob} aria-label="Close">×</button>
            </div>
            <div className="dialog-body">
              {job.description && (
                <div style={{ marginBottom: 20, paddingBottom: 18, borderBottom: '1px solid var(--line-soft)' }}>
                  <div className="eyebrow" style={{ marginBottom: 8 }}>About the role</div>
                  {/* Written by an HR admin and stripped to a short tag allowlist on the server. */}
                  <div className="jd" dangerouslySetInnerHTML={{ __html: job.description }} />
                </div>
              )}

            {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

            <div className="field-row">
              <div className="field">
                <label htmlFor="full_name">Full name <span className="req">*</span></label>
                <input id="full_name" name="full_name" required />
              </div>
              <div className="field">
                <label htmlFor="email">Email <span className="req">*</span></label>
                <input id="email" name="email" type="email" required />
              </div>
              <div className="field">
                <label htmlFor="phone">Mobile number <span className="req">*</span></label>
                <input id="phone" name="phone" required />
              </div>
            </div>

            <div className="field-row">
              <div className="field">
                <label htmlFor="area">Area <span className="req">*</span></label>
                <input id="area" name="area" required placeholder="Ambattur" />
              </div>
              <div className="field">
                <label htmlFor="city">City / Town <span className="req">*</span></label>
                <input id="city" name="city" required placeholder="Chennai" />
              </div>
              <div className="field">
                <label htmlFor="pincode">PIN code <span className="req">*</span></label>
                <input id="pincode" name="pincode" required
                       inputMode="numeric" pattern="[0-9]{6}" maxLength={6}
                       title="Six digits"
                       placeholder="600053" />
              </div>
            </div>

            <div className="field-row">
              <div className="field">
                <label htmlFor="total_experience">Total experience (years)</label>
                <input id="total_experience" name="total_experience" type="number" step="0.5" min="0" defaultValue="0" />
              </div>
              <div className="field">
                <label htmlFor="notice_period_days">Notice period (days)</label>
                <input id="notice_period_days" name="notice_period_days" type="number" min="0" />
              </div>
            </div>

            <div className="field-row">
              <div className="field">
                <label htmlFor="current_ctc">Current annual salary (₹)</label>
                <input id="current_ctc" name="current_ctc" type="number" min="0" />
              </div>
              <div className="field">
                <label htmlFor="expected_ctc">Expected annual salary (₹)</label>
                <input id="expected_ctc" name="expected_ctc" type="number" min="0" />
              </div>
            </div>

            <div className="field">
              <label htmlFor="resume">Resume — PDF or Word, up to 8 MB</label>
              <input id="resume" type="file" accept=".pdf,.doc,.docx,.txt"
                     onChange={(e) => setFile(e.target.files[0] || null)} />
              <p className="sub" style={{ marginTop: 6 }}>
                Attach a resume and our team sees a structured overview of your background straight away.
              </p>
            </div>

            <div className="note">
              This is the short form. If you are called for an interview, you will get a link to the full application
              form to complete on the day.
            </div>

            </div>

            <div className="dialog-foot">
              <button type="button" className="ghost" onClick={closeJob}>Cancel</button>
              <button type="submit" disabled={busy}>{busy ? 'Sending…' : 'Send application'}</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
