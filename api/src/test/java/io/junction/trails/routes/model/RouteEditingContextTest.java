package io.junction.trails.routes.model;

import io.junction.trails.places.model.Place;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class RouteEditingContextTest {
    @Test void preservesOccurrenceOrderAndOwnsItsCollections() {
        var place = place(49, 20);
        var stops = new ArrayList<>(List.of(place, place));
        var preferences = new ArrayList<>(List.of("  quiet scenery  ", "quiet scenery"));
        var context = new RouteEditingContext(UUID.randomUUID(),
                new RouteEditingContext.Endpoint(49, 20, place),
                new RouteEditingContext.Endpoint(50, 21, null), stops, preferences);
        stops.clear(); preferences.clear();
        assertThat(context.stops()).containsExactly(place, place);
        assertThat(context.preferences()).containsExactly("  quiet scenery  ", "quiet scenery");
        assertThatThrownBy(() -> context.stops().clear()).isInstanceOf(UnsupportedOperationException.class);
        assertThatThrownBy(() -> context.preferences().clear()).isInstanceOf(UnsupportedOperationException.class);
    }

    @Test void rejectsInvalidCoordinatesAndMismatchedPlaceBindings() {
        assertThatThrownBy(() -> new RouteEditingContext.Endpoint(Double.NaN, 20, null))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new RouteEditingContext.Endpoint(91, 20, null))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new RouteEditingContext.Endpoint(49, 20.1, place(49, 20)))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test void signedZeroIsNumericallyEqualForBindingValidation() {
        assertThat(new RouteEditingContext.Endpoint(-0.0, 0, place(0, 0)).place()).isNotNull();
    }

    private static Place place(double lat, double lon) {
        return new Place(UUID.randomUUID(), "Fixture", lat, lon, List.of(), List.of(), "manual");
    }
}
