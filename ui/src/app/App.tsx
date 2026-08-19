import { NavLink, Route, Routes } from "react-router-dom";
import { useAuth } from "../auth/auth";

const navigation = ["Home", "World", "Characters", "Quests", "Sessions", "Knowledge", "Ask"];

function Placeholder({ name }: { name: string }) {
  return (
    <section className="panel">
      <p className="eyebrow">Portal foundation</p>
      <h2>{name}</h2>
      <p>This route is ready for its audience-filtered API view.</p>
    </section>
  );
}

function Home() {
  return (
    <div className="dashboard">
      <section className="hero panel">
        <p className="eyebrow">The Sunken Keep</p>
        <h2>Welcome back to the world.</h2>
        <p>Recaps, discoveries, active quests, and character reminders will assemble here.</p>
      </section>
      <section className="panel"><h3>Last session</h3><p>No recap loaded yet.</p></section>
      <section className="panel"><h3>Active quests</h3><p>Connect a campaign to see current objectives.</p></section>
      <section className="panel"><h3>Recent discoveries</h3><p>Knowledge is filtered for the selected perspective.</p></section>
    </div>
  );
}

export function App() {
  const { identity } = useAuth();
  return (
    <div className="app-shell">
      <header>
        <div><p className="eyebrow">Persistent world</p><h1>World Portal</h1></div>
        <div className="context">
          <span>Campaign: The Sunken Keep</span><span>Perspective: Not selected</span>
          <span>{identity?.displayName ?? "Authentication pending"}</span>
        </div>
      </header>
      <nav aria-label="Primary navigation">
        {navigation.map((item) => <NavLink key={item} to={item === "Home" ? "/" : `/${item.toLowerCase()}`}>{item}</NavLink>)}
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          {navigation.slice(1).map((item) => <Route key={item} path={`/${item.toLowerCase()}`} element={<Placeholder name={item} />} />)}
        </Routes>
      </main>
    </div>
  );
}
