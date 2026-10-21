// Show <time datetime="..."> values in the viewer's own time zone.
// The server sends UTC; without JavaScript the UTC text stays.
document.querySelectorAll("time[datetime]").forEach((element) => {
  const moment = new Date(element.dateTime);
  if (!Number.isNaN(moment.getTime())) {
    element.textContent = moment.toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  }
});
