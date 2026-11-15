package io.junction.trails.routes.web;

import io.junction.trails.routes.application.RouteService;
import io.junction.trails.routes.model.Route;
import io.junction.trails.routes.model.NewRoute;
import io.junction.trails.routes.model.RouteEditingContext;
import java.util.Map;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/routes")
@RequiredArgsConstructor
class RouteController {
    private final RouteService routes;

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    Route create(@RequestBody CreateRouteRequest request) {
        return routes.create(request.toCommand());
    }

    @GetMapping("/{id}")
    Route get(@PathVariable UUID id) {
        return routes.get(id);
    }

    @GetMapping("/{id}/editing-context")
    RouteEditingContext editingContext(@PathVariable String id, @RequestParam Map<String, String> parameters) {
        if (!parameters.isEmpty()) { throw NewRoute.invalid("Editing context does not accept query parameters"); }
        return routes.editingContext(RouteRequestIds.required(id));
    }
}
