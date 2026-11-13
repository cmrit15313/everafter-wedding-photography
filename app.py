
<h3>Edit Wedding Details</h3>

<form method="POST"
      action="{{ url_for('edit_event', slug=event['slug']) }}">

    <label>Wedding Title</label>
    <input type="text"
           name="title"
           value="{{ event['title'] }}"
           required>

    <label>Couple Names</label>
    <input type="text"
           name="couple"
           value="{{ event['couple'] or '' }}">

    <label>Wedding Date</label>
    <input type="date"
           name="date"
           value="{{ event['date'] or '' }}">

    <button type="submit">Save Changes</button>
</form>
