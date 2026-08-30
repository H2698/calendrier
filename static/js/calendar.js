document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector(".calendar-card");
  if (!root || !window.FullCalendar) return;
  const canManage = root.dataset.canManage === "true";
  const details = document.getElementById("event-details");
  const createDialog = document.getElementById("appointment-form");
  const syncStatus = document.getElementById("calendar-sync-status");
  const autoSyncMilliseconds = Math.max(5, Number(root.dataset.autoSyncSeconds) || 10) * 1000;
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  const statusLabels = {planned:"Planifié",confirmed:"Confirmé",completed:"Terminé",cancelled:"Annulé",postponed:"Reporté"};

  const apiFetch = async (url, options = {}) => {
    const response = await fetch(url, {credentials:"same-origin", headers:{"Content-Type":"application/json","X-CSRFToken":csrf,...options.headers}, ...options});
    const payload = await response.json();
    if (!response.ok) throw {status: response.status, payload};
    return payload;
  };

  const eventSource = async (info, success, failure) => {
    const params = new URLSearchParams({start:info.startStr,end:info.endStr});
    [["member","filter-member"],["type","filter-type"],["status","filter-status"]].forEach(([key,id]) => { const value=document.getElementById(id).value; if(value) params.set(key,value); });
    try {
      const payload = await apiFetch(`/api/calendar/?${params}`);
      success(payload.data.map(item => ({id:item.id,title:item.title,start:item.start_at,end:item.end_at,backgroundColor:item.members[0]?.color || "#5b4df7",borderColor:"transparent",extendedProps:item})));
      if (syncStatus) {
        syncStatus.classList.remove("error");
        syncStatus.title = `Dernière synchronisation : ${new Date().toLocaleTimeString()}`;
      }
    } catch (error) {
      syncStatus?.classList.add("error");
      failure(error);
    }
  };

  const moveEvent = async (info) => {
    if (!confirm(`Déplacer ce rendez-vous ?\n${info.oldEvent.start.toLocaleString()} → ${info.event.start.toLocaleString()}`)) return info.revert();
    const body = {start_at:info.event.start.toISOString(),end_at:(info.event.end || info.event.start).toISOString()};
    try { await apiFetch(`/api/appointments/${info.event.id}/move/`, {method:"POST",body:JSON.stringify(body)}); }
    catch (error) {
      if (error.status === 409 && confirm("Un membre possède déjà un rendez-vous. Déplacer quand même ?")) {
        body.force_conflicts = true;
        try { await apiFetch(`/api/appointments/${info.event.id}/move/`, {method:"POST",body:JSON.stringify(body)}); return; } catch (_) {}
      }
      info.revert();
    }
  };

  const calendar = new FullCalendar.Calendar(document.getElementById("calendar"), {
    locale:"fr",initialView:window.innerWidth < 620 ? "listDay" : "dayGridMonth",height:"auto",nowIndicator:true,editable:canManage,eventStartEditable:canManage,eventDurationEditable:canManage,
    headerToolbar:{left:"prev,next today",center:"title",right:"dayGridMonth,timeGridWeek,timeGridDay"},
    events:eventSource,eventDrop:moveEvent,eventResize:moveEvent,
    eventContent(arg) { const dots=arg.event.extendedProps.members.map(m=>`<i class="event-member-dot" style="--dot:${m.color}"></i>`).join(""); return {html:`<span class="event-time">${arg.timeText}</span><span class="event-title">${arg.event.title}</span><span class="event-dots">${dots}</span>`}; },
    eventClick(info) { const item=info.event.extendedProps; document.getElementById("detail-type").textContent=item.appointment_type.name; document.getElementById("detail-title").textContent=info.event.title; document.getElementById("detail-list").innerHTML=`<div><dt>Horaire</dt><dd>${info.event.start.toLocaleString()} – ${info.event.end?.toLocaleTimeString() || ""}</dd></div><div><dt>Statut</dt><dd>${statusLabels[item.status] || item.status}</dd></div><div><dt>Membres</dt><dd>${item.members.map(m=>m.name).join(", ") || "—"}</dd></div>${item.client?`<div><dt>Client</dt><dd>${item.client.name}<br>${item.client.phone || ""}</dd></div>`:""}`; document.getElementById("detail-notes").textContent=item.notes || ""; details.showModal(); }
  });
  calendar.render();
  const refreshVisibleCalendar = () => {
    if (document.visibilityState === "visible" && !document.querySelector("dialog[open]")) {
      calendar.refetchEvents();
    }
  };
  window.setInterval(refreshVisibleCalendar, autoSyncMilliseconds);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refreshVisibleCalendar();
  });
  ["filter-member","filter-type","filter-status"].forEach(id=>document.getElementById(id).addEventListener("change",()=>calendar.refetchEvents()));
  document.querySelectorAll("[data-close]").forEach(button=>button.addEventListener("click",()=>button.closest("dialog").close()));
  document.getElementById("new-appointment")?.addEventListener("click",()=>createDialog.showModal());
  document.getElementById("appointment-create-form")?.addEventListener("submit", async event => {
    event.preventDefault(); const form=new FormData(event.currentTarget); const body=Object.fromEntries(form); body.member_ids=form.getAll("member_ids").map(Number);
    if (body.recurrence_frequency) body.recurrence={frequency:body.recurrence_frequency,interval_value:1,end_date:body.recurrence_end_date};
    delete body.recurrence_frequency; delete body.recurrence_end_date;
    try { await apiFetch("/api/appointments/",{method:"POST",body:JSON.stringify(body)}); createDialog.close(); event.currentTarget.reset(); calendar.refetchEvents(); }
    catch (error) { if(error.status===409 && confirm("Conflit détecté. Créer quand même ?")){ body.force_conflicts=true; try{await apiFetch("/api/appointments/",{method:"POST",body:JSON.stringify(body)});createDialog.close();calendar.refetchEvents();}catch(_){alert("Création impossible.");}} else alert("Vérifiez les informations du rendez-vous."); }
  });
});
