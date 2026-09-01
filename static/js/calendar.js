document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector(".calendar-card");
  if (!root || !window.FullCalendar) return;

  const canManage = root.dataset.canManage === "true";
  const details = document.getElementById("event-details");
  const formDialog = document.getElementById("appointment-form");
  const formElement = document.getElementById("appointment-create-form");
  const syncStatus = document.getElementById("calendar-sync-status");
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  const autoSyncMilliseconds = Math.max(5, Number(root.dataset.autoSyncSeconds) || 10) * 1000;
  const statusLabels = {planned:"Planifié", confirmed:"Confirmé", completed:"Terminé", cancelled:"Annulé", postponed:"Reporté"};
  const mobileCalendar = window.innerWidth < 620;
  let selectedEvent = null;

  const apiFetch = async (url, options = {}) => {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: {"Content-Type":"application/json", "X-CSRFToken":csrf, ...options.headers},
      ...options,
    });
    const payload = await response.json();
    if (!response.ok) throw {status: response.status, payload};
    return payload;
  };

  const eventSource = async (info, success, failure) => {
    const params = new URLSearchParams({start:info.startStr, end:info.endStr});
    [["member","filter-member"], ["type","filter-type"], ["status","filter-status"]].forEach(([key, id]) => {
      const value = document.getElementById(id).value;
      if (value) params.set(key, value);
    });
    try {
      const payload = await apiFetch(`/api/calendar/?${params}`);
      success(payload.data.map((item) => ({
        id:item.id, title:item.title, start:item.start_at, end:item.end_at,
        backgroundColor:item.members[0]?.color || "#5b4df7",
        borderColor:"transparent", extendedProps:item,
      })));
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
    if (!confirm(`Déplacer ce rendez-vous ?\n${info.oldEvent.start.toLocaleString()} → ${info.event.start.toLocaleString()}`)) {
      info.revert();
      return;
    }
    const body = {
      start_at:info.event.start.toISOString(),
      end_at:(info.event.end || info.event.start).toISOString(),
    };
    try {
      await apiFetch(`/api/appointments/${info.event.id}/move/`, {method:"POST", body:JSON.stringify(body)});
    } catch (error) {
      if (error.status === 409 && confirm("Un membre possède déjà un rendez-vous. Déplacer quand même ?")) {
        body.force_conflicts = true;
        try {
          await apiFetch(`/api/appointments/${info.event.id}/move/`, {method:"POST", body:JSON.stringify(body)});
          return;
        } catch (_) {}
      }
      info.revert();
    }
  };

  const detailRow = (label, value, link) => {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    if (link) {
      const anchor = document.createElement("a");
      anchor.href = link;
      anchor.textContent = value;
      description.append(anchor);
    } else {
      description.textContent = value;
    }
    wrapper.append(term, description);
    return wrapper;
  };

  const openDetails = (info) => {
    selectedEvent = info.event;
    const item = info.event.extendedProps;
    document.getElementById("detail-type").textContent = item.appointment_type.name;
    document.getElementById("detail-title").textContent = info.event.title;
    const list = document.getElementById("detail-list");
    list.replaceChildren(
      detailRow("Horaire", `${info.event.start.toLocaleString()} – ${info.event.end?.toLocaleTimeString() || ""}`),
      detailRow("Statut", statusLabels[item.status] || item.status),
      detailRow("Membres", item.members.map((member) => member.name).join(", ") || "—"),
    );
    if (item.client) {
      list.append(detailRow("Client", item.client.name, canManage ? `/clients/${encodeURIComponent(item.client.id)}/` : null));
      if (item.client.phone) list.append(detailRow("Téléphone", item.client.phone));
      if (item.client.email) list.append(detailRow("E-mail", item.client.email));
    }
    if (item.description) list.append(detailRow("Description", item.description));
    document.getElementById("detail-notes").textContent = item.notes || "";
    details.showModal();
  };

  const eventContent = (arg) => {
    const time = document.createElement("span");
    time.className = "event-time";
    time.textContent = arg.timeText;
    const title = document.createElement("span");
    title.className = "event-title";
    title.textContent = arg.event.title;
    const dots = document.createElement("span");
    dots.className = "event-dots";
    arg.event.extendedProps.members.forEach((member) => {
      const dot = document.createElement("i");
      dot.className = "event-member-dot";
      dot.style.setProperty("--dot", member.color);
      dots.append(dot);
    });
    return {domNodes:[time, title, dots]};
  };

  const calendar = new FullCalendar.Calendar(document.getElementById("calendar"), {
    locale:"fr", initialView:mobileCalendar ? "listDay" : "dayGridMonth",
    height:"auto", nowIndicator:true, editable:canManage,
    eventStartEditable:canManage, eventDurationEditable:canManage,
    headerToolbar:{left:"prev,next today", center:"title", right:mobileCalendar ? "listDay,listWeek" : "dayGridMonth,timeGridWeek,timeGridDay"},
    events:eventSource, eventDrop:moveEvent, eventResize:moveEvent,
    eventContent, eventClick:openDetails,
  });
  calendar.render();

  const localInputValue = (value) => {
    const date = new Date(value);
    const offsetDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return offsetDate.toISOString().slice(0, 16);
  };

  const prepareCreate = () => {
    formElement.reset();
    delete formElement.dataset.appointmentId;
    document.getElementById("appointment-form-title").textContent = "Nouveau rendez-vous";
    document.getElementById("appointment-submit").textContent = "Créer";
    document.getElementById("appointment-recurrence").disabled = false;
    document.getElementById("recurrence-end").disabled = false;
    formDialog.showModal();
  };

  const prepareEdit = () => {
    if (!selectedEvent) return;
    const item = selectedEvent.extendedProps;
    formElement.reset();
    formElement.dataset.appointmentId = item.id;
    formElement.elements.title.value = item.title;
    formElement.elements.client_id.value = item.client?.id || "";
    formElement.elements.appointment_type_id.value = item.appointment_type.id;
    formElement.elements.start_at.value = localInputValue(item.start_at);
    formElement.elements.end_at.value = localInputValue(item.end_at);
    formElement.elements.status.value = item.status;
    formElement.elements.description.value = item.description || "";
    formElement.elements.notes.value = item.notes || "";
    const memberIds = new Set(item.members.map((member) => String(member.id)));
    formElement.querySelectorAll('[name="member_ids"]').forEach((input) => {
      input.checked = memberIds.has(input.value);
    });
    document.getElementById("appointment-form-title").textContent = "Modifier le rendez-vous";
    document.getElementById("appointment-submit").textContent = "Enregistrer";
    document.getElementById("appointment-recurrence").disabled = true;
    document.getElementById("recurrence-end").disabled = true;
    details.close();
    formDialog.showModal();
  };

  const submitAppointment = async (event) => {
    event.preventDefault();
    const form = new FormData(formElement);
    const body = Object.fromEntries(form);
    delete body.csrfmiddlewaretoken;
    body.member_ids = form.getAll("member_ids").map(Number);
    const appointmentId = formElement.dataset.appointmentId;
    if (!appointmentId && body.recurrence_frequency) {
      body.recurrence = {frequency:body.recurrence_frequency, interval_value:1, end_date:body.recurrence_end_date};
    }
    delete body.recurrence_frequency;
    delete body.recurrence_end_date;
    const url = appointmentId ? `/api/appointments/${appointmentId}/` : "/api/appointments/";
    const method = appointmentId ? "PATCH" : "POST";
    try {
      await apiFetch(url, {method, body:JSON.stringify(body)});
    } catch (error) {
      if (error.status === 409 && confirm("Conflit détecté. Enregistrer quand même ?")) {
        body.force_conflicts = true;
        try {
          await apiFetch(url, {method, body:JSON.stringify(body)});
        } catch (_) {
          alert("Enregistrement impossible.");
          return;
        }
      } else {
        alert("Vérifiez les informations du rendez-vous.");
        return;
      }
    }
    formDialog.close();
    formElement.reset();
    calendar.refetchEvents();
  };

  const cancelSelected = async () => {
    if (!selectedEvent || !confirm("Annuler ce rendez-vous ?")) return;
    try {
      await apiFetch(`/api/appointments/${selectedEvent.id}/cancel/`, {method:"POST"});
      details.close();
      calendar.refetchEvents();
    } catch (_) {
      alert("Annulation impossible.");
    }
  };

  const deleteSelected = async () => {
    if (!selectedEvent) return;
    const confirmation = `Supprimer « ${selectedEvent.title} » du calendrier ?\nCette action concerne uniquement ce rendez-vous et restera visible dans l’historique.`;
    if (!confirm(confirmation)) return;
    try {
      await apiFetch(`/api/appointments/${selectedEvent.id}/delete/`, {method:"POST"});
      details.close();
      selectedEvent = null;
      calendar.refetchEvents();
    } catch (_) {
      alert("Suppression impossible.");
    }
  };

  const createQuickClient = async () => {
    const name = prompt("Nom du nouveau client :")?.trim();
    if (!name) return;
    try {
      const payload = await apiFetch("/api/clients/", {method:"POST", body:JSON.stringify({name})});
      const option = new Option(payload.data.name, payload.data.id, true, true);
      document.getElementById("appointment-client").add(option);
    } catch (_) {
      alert("Création du client impossible.");
    }
  };

  const refreshVisibleCalendar = () => {
    if (document.visibilityState === "visible" && !document.querySelector("dialog[open]")) {
      calendar.refetchEvents();
    }
  };
  window.setInterval(refreshVisibleCalendar, autoSyncMilliseconds);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refreshVisibleCalendar();
  });
  ["filter-member", "filter-type", "filter-status"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => calendar.refetchEvents());
  });
  document.querySelectorAll("[data-close]").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog").close());
  });
  document.getElementById("new-appointment")?.addEventListener("click", prepareCreate);
  document.getElementById("edit-appointment")?.addEventListener("click", prepareEdit);
  document.getElementById("cancel-appointment")?.addEventListener("click", cancelSelected);
  document.getElementById("delete-appointment")?.addEventListener("click", deleteSelected);
  document.getElementById("quick-client")?.addEventListener("click", createQuickClient);
  formElement?.addEventListener("submit", submitAppointment);

  const pageUrl = new URL(window.location.href);
  if (canManage && formElement && formDialog && pageUrl.searchParams.get("new") === "1") {
    prepareCreate();
    // Consume the shortcut so refreshing the calendar does not reopen the form.
    pageUrl.searchParams.delete("new");
    window.history.replaceState(
      window.history.state, "", `${pageUrl.pathname}${pageUrl.search}${pageUrl.hash}`,
    );
  }
});
